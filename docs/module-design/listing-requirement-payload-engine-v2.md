# Listing Requirement & Payload Engine V2 Module Design

> Status: In Progress
> Owner: amz-listing-management-system
> Epic: `EPIC-AMZ-LISTING-REQUIREMENT-PAYLOAD-V2`
> Decision: `docs/decisions/ADR-2026-06-26-listing-requirement-payload-engine-v2.md`

## Current Implementation Status

Updated: 2026-06-27 by Codex (S14 regression evaluator + cutover plan first pass).

This module set is currently implemented as read-only / standalone V2
foundation code. It does not replace the production `generate-listing-api`
pipeline yet.

Current completion estimate:

- production replacement: **50% - 55%**
- read-only / shadow-plan foundation: **about 95%**

Implemented first-pass modules:

| Module | Status |
| --- | --- |
| `requirement_models_v2.py` | Implemented dataclass contracts and serializers. |
| `schema_condition_evaluator_v2.py` | Implemented conservative condition evaluator and unsupported-condition traces. |
| `requirement_tree_builder_v2.py` | Implemented applicable RequirementTree builder with condition trace reporting; learned-required hook for S11. |
| `evidence_resolver_v2.py` | Implemented path/default/review-override ResolutionTree resolver; LLM source integrated via `LLMAttributeExtractorV2`. |
| `llm_attribute_extractor_v2.py` | Implemented path-level LLM extraction with enum lock, null-on-absent, evidence-bound, confidence cap. |
| `payload_composer_v2.py` | Implemented generic renderer for list value, measure, object, nested object, and array object shapes. |
| `coverage_gate_v2.py` | Implemented tree-level required coverage and review/default policy gate. |
| `confidence_scorer_v2.py` | Implemented path-level scoring with evidence-grounded signals and conservative parent aggregation. |
| `amazon_listing_pending_review_v2_repository.py` | Implemented V2 path-level review persistence with UNIQUE constraint for resume replay idempotency. |
| `review_adapter_v2.py` | Implemented extract/persist/review/build_overrides/submit_reviewed_paths; CLI wired with `--engine v1\|v2` flag. |
| `validation_preview_v2.py` | Implemented Amazon VALIDATION_PREVIEW integration with audit persistence and V2 coverage comparison. |
| `feedback_learning_adapter_v2.py` | Implemented V2 feedback learning from Amazon 90220 issues at path_key granularity; tree builder hook + CLI task. |
| `amazon_listing_learned_required_paths_v2_repository.py` | Implemented upsert/list with sample_count ratcheting; UNIQUE on (category, path_key, path_key_version). |
| `listing_payload_shadow_adapter_v2.py` | Implemented S12 shadow audit adapter that builds V2 beside V1 and persists read-only audit rows. |
| `listing_payload_shadow_diff_v2.py` | Implemented S13 read-only V1/V2 shadow diff summaries from audit rows. |
| `listing_payload_v2_regression.py` | Implemented S14 shadow evidence evaluator for category go/no-go decisions. |
| `listing_payload_engine_v2.py` | Implemented read-only requirement analysis and `build_read_only_plan()`; wires LLM extraction, confidence scoring, and path-level review state. |

Not implemented yet:

- real multi-category shadow/strict-preview evidence collection
- `LISTING_PAYLOAD_ENGINE=v2` replacement implementation and canary cutover

Current verification:

```text
V2 targeted tests: 78 passed
Full unit + integration suite: 871 passed
S5/S6/S7 wiring fix targeted tests: 35 passed
S12 shadow adapter targeted tests: 8 passed
S13 shadow diff targeted tests: 34 passed
S14 regression evaluator targeted tests: 29 passed
ruff: All checks passed
```

**Known debt**:

- `src/cli/operation_handlers.py` is at 1525 lines (red line 500). This is pre-existing cumulative debt from S6–S11 V2 handler additions. Refactor target: extract V2 handlers into `src/cli/operation_handlers_v2.py` before S14 cutover. Tracked in TODO.md retirement debt.


### S5 Implementation Notes

`llm_attribute_extractor_v2.py` (142 lines) extracts path-level candidate values:

- Input: `AmazonListingDraft` + `RequirementNode` (carries `path_key`, `shape`, `enum_values`, `unit_values`).
- Sensitive path guard: blocks `brand`, `manufacturer`, identifiers, compliance, certification paths based on `path_key` root.
- Enum lock: when `requirement.enum_values` is non-empty, LLM-returned value is canonicalized against the enum; invalid enum returns null with `invalid_enum` warning.
- Null-on-absent: empty value → `not_found`; empty evidence → `missing_evidence`.
- Confidence cap: `low` stays `low`, everything else caps to `medium` (V2 does not allow `high` from LLM).
- Reuses V1 `LLMAttributeExtraction` dataclass and V1 `AttributeExtractionLLMClient` (context carries both V1 fields and V2-specific `path_key`/`shape`/`unit_values`).

`evidence_resolver_v2.py` integration:

- `__init__` accepts optional `llm_extractor` parameter.
- `_read_source` `llm` branch calls `llm_extractor.extract(draft, requirement)` when extractor is configured; falls back to defer behavior (`None`, `"llm"`, `"low"`) when not.
- LLM extraction failure (null value) allows fallback to subsequent sources in the rule's `sources` list.
- `ListingPayloadEngineV2.build_read_only_plan()` injects `LLMAttributeExtractorV2` into the resolver by default. The default extractor remains environment-gated (`ATTRIBUTE_LLM_EXTRACTION_ENABLED`) and is injectable in tests.

### S6 Implementation Notes

`confidence_scorer_v2.py` (307 lines) scores V2 `ResolutionNode` paths and
aggregates parent review state conservatively.

- Input: `ResolutionNode` + `AmazonListingDraft` + `RequirementNode` (carries `shape`, `enum_values`, `path_key`).
- Policy: reuses `config/listing_gates/review_policy.yaml` (same weights and thresholds as V1).
- Sensitive path guard: `path_key` root in `{brand, manufacturer, item_identifier, product_identifier, compliance, certification}` → route `human`, score 0.
- Safe default: `resolution.safe_default=True` → route `auto_approved`, score 100 (pre-approved).
- Missing value: empty value on a leaf → route `human`, score 0.
- Leaf signals (same as V1, keyed by `path_key`):
  - `evidence_context_match` (45) — evidence text appears in draft context (title, bullets, description, search terms, generic keyword, product attributes).
  - `evidence_min_length` (10) — evidence length >= `evidence_min_length` (default 20).
  - `enum_valid` (15) — value matches `requirement.enum_values`.
  - `llm_confidence_not_low` (10) — `resolution.confidence != "low"`.
  - `history_accuracy` (20) — from `history_provider.get_attribute_accuracy(product_type, path_key, min_samples)`.
- Route thresholds (same as V1): `auto_approved >= 55`, `ai_agent >= 35`, else `human`.
- Parent aggregation (object / nested_object / array_object / measure / root shapes):
  - Walks tree in post-order so children are scored before parents.
  - Parent route = worst (max priority) child route (`human > ai_agent > auto_approved`).
  - Parent score = min(child scores).
  - Parent without children → route `human`, score 0.
- `score_tree(resolution_root, draft, requirement_root)` mutates each node's `confidence_score` and `review_route` in place.
- `score_node(resolution, draft, requirement)` returns `PathConfidenceScore` for a single node without mutation.
- Context provider is injectable via `__init__` (`context_provider(draft, requirement) -> str`); defaults to a built-in text collector over `draft.content` and `draft.standard_product.attributes`.
- `ListingPayloadEngineV2.build_read_only_plan()` now calls `score_tree()` before payload composition and coverage evaluation, so downstream gates consume scored `ResolutionNode` state instead of unscored placeholders.

### S7 Implementation Notes

S7 delivers V2 path-level review persistence and the review workflow adapter.

**Migration** (`migrations/amz_listing_pending_review_v2.sql` + `alembic/versions/011_amz_listing_pending_review_v2.py`):

- One row = one path-level review item (not SKU-level like V1).
- `UNIQUE (category, sku, path_key, path_key_version)` guarantees stable path_key replay idempotency.
- Indexes: `(path_key, review_status)` for S11 feedback aggregation; `(review_status, category, created_at)` for pending list; `(sku)` for SKU queries.
- `plan_snapshot` stored redundantly per row so V2 table is self-contained; V1 table can be `@retire`d without affecting V2.

**Repository** (`amazon_listing_pending_review_v2_repository.py`, 255 lines):

- `upsert_pending_paths(items)` — INSERT ON CONFLICT DO UPDATE, resets to `review_status='pending'` on replay.
- `list_pending(category, status, route, limit)` — filtered pending list.
- `list_for_sku(category, sku)` — all items for one SKU.
- `save_decision(review_id, decision, reviewer, verdict, review_status)` — updates single path decision with `decided_at=NOW()`.
- `list_approved_for_sku(category, sku)` — approved decisions for override replay.
- `list_completed_skus(category, limit)` — DISTINCT SKUs with completed reviews, for submit side.
- `get_path_accuracy(product_type, path_key, min_samples)` — historical accuracy by path_key (for S11 feedback learning).

**Adapter** (`review_adapter_v2.py`, 219 lines):

- `persist_pending_paths(category, sku, parent_sku, path_key_version, plan_snapshot, resolution_root)` — extracts pending leaf paths from ResolutionTree and upserts. Returns count.
- `review_pending_paths(category, limit)` — loads all pending items; for `ai_agent` route runs `AttributeReviewAgent`, saves decision; for `human` route just counts as `human_required`.
- `build_overrides_from_decisions(category, sku)` — loads approved decisions, returns `{path_key: {value, evidence, confidence, review_status, source: "review_override", ...}}` for `EvidenceResolverV2.resolve(overrides=...)`.
- `submit_reviewed_paths(category, dry_run, limit)` — for each SKU with completed reviews, builds overrides, calls `ListingPayloadEngineV2.build_read_only_plan(rules, overrides)`, returns coverage result. Does not PUT to Amazon (deferred to S14 cutover).
- `_extract_pending_paths` — walks ResolutionTree leaves; a pending leaf has: no children, non-empty value, `review_route in {ai_agent, human}`, `blocking=True`.
- `_attribute_from_path_key` — derives top-level attribute from path_key's first segment (e.g., `frame.color` → `frame`).
- Engine review-state mapping: after scoring, required LLM leaves with `review_route in {ai_agent, human}` are marked `review_status="pending"`, `blocking=True`, and `NEEDS_REVIEW_REQUIRED_ATTRIBUTE`; required leaves routed `auto_approved` are marked `review_status="auto_approved"`. This is the contract shared by `coverage_gate_v2.py` and `review_adapter_v2.py`.

**CLI Integration**:

- `--engine v1|v2` flag added to `main.py` (default `v1`, also reads `LISTING_PAYLOAD_ENGINE` env var).
- `review-pending-attributes --engine v2` → `ReviewAdapterV2.review_pending_paths()`.
- `submit-reviewed-plans --engine v2` → `ReviewAdapterV2.submit_reviewed_paths()` (dry-run only; no PUT).
- V1 behavior unchanged when `--engine v1` (default).

**Resume determinism**: guaranteed by the UNIQUE constraint. Re-running `persist_pending_paths` for the same SKU resets all path items to `pending` and clears previous decisions — replay is safe and idempotent.

### S10 Implementation Notes

S10 delivers V2 Amazon VALIDATION_PREVIEW integration: V2 plans can run
Amazon's server-side validation without PUT, persist comparable audit results,
and surface a diff against V2 coverage findings.

**Module** (`validation_preview_v2.py`, 211 lines):

- `preview(plan: PayloadBuildPlan) -> ValidationPreviewResult` — extracts `plan.attributes`, calls `AmazonListingsClient.validation_preview(sku, product_type, attributes)` (PUT with `mode=VALIDATION_PREVIEW`, no listing created), persists audit row via `AmazonAPISubmissionRepository.insert_submission()`.
- `compare(plan, result) -> ValidationPreviewComparison` — matches Amazon issues (by `attributeNames[0]` root) against V2 coverage findings (by `path_key` root); classifies into `matched` / `amazon_only` / `v2_only`.
- Status strings (same as V1 for comparable audit): `validation_preview_passed` (no issues), `validation_preview_issues` (Amazon returned issues), `validation_preview_failed` (API call raised).
- `request_payload` stored with `strictDryRun: True` and `engine: "v2"` markers to distinguish V2 preview rows from V1 in `amazon_api_submissions`.
- Failures (exceptions) still persist a row with `error_message` and `status="validation_preview_failed"` so the audit trail is complete.

**CLI task**: `validate-listing-v2 --category X --sku Y`

1. Loads rules via `AttributeRuleLoader`.
2. Builds V2 plan via `ListingPayloadEngineV2.build_read_only_plan()`.
3. Calls `ValidationPreviewV2.preview(plan)` → Amazon VALIDATION_PREVIEW (no PUT).
4. Calls `ValidationPreviewV2.compare(plan, result)`.
5. Prints status, issue counts, and diff (Amazon-only issues first, then V2-only findings).
6. Returns structured result for programmatic use.

**Comparison semantics**:

- `matched`: Amazon issue's `attributeNames[0]` root matches a V2 finding's `path_key` root (e.g., Amazon `frame_material` issue ↔ V2 `frame_material` finding).
- `amazon_only`: Amazon flagged but V2 coverage gate missed — V2 false negative.
- `v2_only`: V2 flagged but Amazon accepted — V2 false positive (over-strict).

This comparison feeds directly into S14 (regression and cutover) — it tells us whether V2 catches what Amazon catches before cutover.

### S11 Implementation Notes

S11 closes the feedback loop: when Amazon returns 90220 (missing-required) on a
V2 submission, the missing attributes are learned at path_key granularity and
injected back into the V2 tree builder on the next build. Unlike V1, which
blindly forced the entire product type's attribute set, V2 records each missing
attribute as a stable path_key and only injects the ones Amazon actually flagged.

**Migration** (`migrations/amz_listing_learned_required_paths_v2.sql` + alembic 012):

```sql
CREATE TABLE amz_listing_learned_required_paths_v2 (
    id BIGSERIAL PRIMARY KEY,
    category VARCHAR(64),
    path_key TEXT,
    path_key_version VARCHAR(32),
    attribute VARCHAR(128),
    source_submission_id BIGINT,
    sample_count INT DEFAULT 1,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (category, path_key, path_key_version)
);
-- Indexes on (category, path_key_version), (category, last_seen_at DESC)
```

`sample_count` and `last_seen_at` ratchet on each repeated 90220 sighting so
operators can see which path_keys Amazon flags repeatedly across submissions.

**Repository** (`amazon_listing_learned_required_paths_v2_repository.py`, 81 lines):

- `upsert_learned(category, path_key, path_key_version, attribute, source_submission_id)` — INSERT ON CONFLICT (category, path_key, path_key_version) DO UPDATE SET sample_count = sample_count + 1, last_seen_at = NOW().
- `list_for_category(category) -> List[str]` — returns distinct path_keys for a category, ordered by last_seen_at DESC.
- `list_for_category_and_paths(category, path_keys) -> List[str]` — filters an incoming path_key set against stored rows (used by tree builder to skip unknown path_keys without a second round-trip).

**Adapter** (`feedback_learning_adapter_v2.py`, 113 lines):

- `learn_from_submission(submission) -> int` — parses `response_body.issues` for code 90220, extracts `attributeNames`, upserts each as a path_key. Returns count of learned path_keys.
- `learn_from_recent_submissions(category, limit=100) -> Dict[str, int]` — pulls recent submissions containing 90220 issues via `AmazonAPISubmissionRepository.list_submissions_with_issue_code()` and feeds each to `learn_from_submission`. Returns `{"submissions_scanned": N, "paths_learned": M}`.
- `get_learned_required_paths(category) -> List[str]` — delegates to repository's `list_for_category`.
- `MISSING_REQUIRED_CODE = "90220"`, `DEFAULT_PATH_KEY_VERSION = "v2_path_keys_2026_06"`.

**Submission repo extension** (`amazon_api_submission_repository.py`):

- New `list_submissions_with_issue_code(product_type, issue_code, limit)` queries `amazon_api_submissions` for rows whose `response_body->'issues'` contains an entry with the given `code`, via JSONB `EXISTS` subquery. Reused by V2 adapter (no V1 callers affected).

**Tree builder hook** (`requirement_tree_builder_v2.py`):

- `build()` accepts a new `learned_required_paths: List[str] | None = None` parameter.
- `_inject_learned_required(required, learned_required_paths, properties)` adds each learned path_key's root attribute (top-level property) to the required list if — and only if — it exists in the schema's `properties` and isn't already required. Defensive against unknown path_keys Amazon may surface that the schema doesn't know about yet.
- Only the root attribute is injected (not nested paths); Amazon 90220 always surfaces top-level attribute names, so we don't need to recurse.

**CLI task**: `learn-required-from-submissions --product-type X` (or `--category X`)

1. Resolves `product_type` from `--product-type` or `--category`.
2. Calls `FeedbackLearningAdapterV2.learn_from_recent_submissions(category, limit=100)`.
3. Calls `get_learned_required_paths(category)` to print current learned set.
4. Prints summary: `submissions_scanned`, `paths_learned`, learned path_keys.

**Why path_key granularity matters**: V1 forced the entire product type's
required attribute set whenever any 90220 fired, leading to over-strict
rejections on subsequent attempts. V2 only forces the specific attributes Amazon
actually flagged, so a single missing `frame_material` no longer drags in
`seat_material_type`, `weight_capacity`, etc.

## 1. Purpose

V2 replaces the flat Amazon listing attribute pipeline with a tree-shaped engine
that understands conditional requirements, object children, path-level evidence,
path-level confidence, review routing, and generic Listings Items API payload
rendering.

The module boundary replaces these current responsibilities:

- flat attribute required list
- flat `AttributeResolver`
- flat `AttributePayloadRenderer`
- top-level `AmazonListingAttributeCoverageGate`
- top-level review routing for required LLM attributes

It does not replace:

- commercial gate
- variation resolver
- image selector
- listing quality gate
- Amazon submitter
- order, pricing, inventory, PPC, lifecycle modules

## 2. Core Objects

### 2.1 RequirementNode

One schema node in the current listing scenario.

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `path_key` | `str` | Stable path key, e.g. `frame.color`. |
| `schema_path` | `str` | Location in Amazon schema for debugging. |
| `name` | `str` | Node name relative to parent. |
| `shape` | `str` | `list_value`, `measure`, `object`, `nested_object`, `array_object`, `scalar`, etc. |
| `required` | `bool` | Required for this listing scenario. |
| `required_children` | `list[str]` | Child names required by this node. |
| `children` | `list[RequirementNode]` | Recursive child nodes. |
| `enum_values` | `list[str]` | Allowed values when schema provides enum. |
| `unit_values` | `list[str]` | Allowed units for measure nodes. |
| `selectors` | `list[str]` | Amazon selectors for array object identity. |
| `auto_fields` | `dict` | Values such as `language_tag` and `marketplace_id` that can be injected. |
| `condition_trace` | `list[ConditionTrace]` | Why this node is required, not required, or unknown. |
| `condition_state` | `str` | `matched`, `not_matched`, `unknown`, or `unconditional`. |

### 2.2 ConditionTrace

Explains condition evaluation.

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_path` | `str` | JSON schema path for the condition. |
| `operator` | `str` | `if`, `then`, `else`, `allOf`, `anyOf`, `oneOf`, `not`, `contains`, etc. |
| `result` | `str` | `true`, `false`, `unknown`, or `unsupported`. |
| `reason` | `str` | Human-readable evaluation reason. |
| `dependent_paths` | `list[str]` | Payload paths the condition used. |
| `introduced_required_paths` | `list[str]` | Paths made required by this condition. |
| `non_applicable_required_paths` | `list[str]` | Paths considered by the opposite branch and not required for the current payload. |
| `unknown_required_paths` | `list[str]` | Paths that may become required but are blocked by unknown or unsupported condition evaluation. |

### 2.3 ResolutionNode

One resolved or unresolved value for a requirement path.

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `path_key` | `str` | Stable path key matching `RequirementNode.path_key`. |
| `value` | `Any` | Resolved value before final payload rendering. |
| `source` | `str` | `path`, `derived`, `llm`, `default`, `review_override`, or empty. |
| `evidence` | `str` | Source evidence for the value. |
| `confidence` | `str` | Existing label: `low`, `medium`, `high`. |
| `confidence_score` | `int | None` | Evidence-grounded objective score. |
| `review_status` | `str` | `auto_approved`, `pending`, `completed`, etc. |
| `review_route` | `str` | `auto_approved`, `ai_agent`, `human`, etc. |
| `safe_default` | `bool` | True only for explicit path-level safe defaults. |
| `blocking` | `bool` | Whether this path blocks payload submission. |
| `blocking_codes` | `list[str]` | Machine-readable blocking reasons. |
| `children` | `list[ResolutionNode]` | Recursive child resolutions. |

### 2.4 PayloadBuildPlan

The V2 output consumed by the existing listing orchestration.

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `sku` | `str` | Listing SKU. |
| `product_type` | `str` | Amazon product type. |
| `attributes` | `dict` | Final Listings Items API attributes payload. |
| `requirement_tree` | `RequirementNode` | Applicable requirement tree. |
| `resolution_tree` | `ResolutionNode` | Path-level resolution tree. |
| `covered_required_paths` | `list[str]` | Required paths fully covered. |
| `missing_required_paths` | `list[str]` | Required paths with no usable value. |
| `low_confidence_required_paths` | `list[str]` | Required paths blocked by confidence. |
| `pending_review_paths` | `list[str]` | Required paths awaiting review. |
| `safe_default_paths` | `list[str]` | Required paths filled by approved safe defaults. |
| `condition_traces` | `list[ConditionTrace]` | Full condition evaluation audit. |
| `path_key_version` | `str` | Stable path key algorithm version. |
| `iteration_count` | `int` | Requirement/resolution convergence iterations. |
| `non_converged` | `bool` | True when iteration limit was reached. |
| `findings` | `list[dict]` | Coverage and condition findings. |

## 3. Stable Path Key Contract

Stable path keys are review identifiers. They must not depend on incidental list
indexes unless the index is part of Amazon's stable schema identity.

Rules:

1. Plain object children use dot paths:

   ```text
   frame.color
   seat.material_type
   ```

2. Measure components use semantic child keys:

   ```text
   maximum_weight_recommendation.value
   maximum_weight_recommendation.unit
   ```

3. Array object entries use schema selectors when available:

   ```text
   frame{marketplace_id=ATVPDKIKX0DER}.color
   ```

4. If a selector is not available, V2 creates a deterministic fingerprint from:

   ```text
   schema_path + normalized_required_child_values + marketplace_id
   ```

5. If the fingerprint cannot be built before review, the path is marked
   `non_resumable` and routed fail-closed.

6. The path key algorithm version is recorded as:

   ```text
   path_key_version = "v2_path_keys_2026_06"
   ```

7. Review overrides target path keys, not display labels. Override replay must
   not require another LLM extraction call.

## 4. Conditional Evaluation Contract

The evaluator implements a conservative subset first:

| Schema construct | Phase 1 behavior |
| --- | --- |
| `required` | True when all named payload paths are present and non-empty. |
| `properties` | Evaluate known child predicates when payload value exists. |
| `enum` / `const` | Compare normalized payload values. |
| `contains` | True when any array item matches the child predicate. |
| `allOf` | All children true; unknown if any child unknown and none false. |
| `anyOf` | Any child true; unknown if no true and at least one unknown. |
| `oneOf` | Exactly one true; unknown if truth count cannot be decided. |
| `not` | Invert true/false; unknown remains unknown. |
| `if` / `then` / `else` | Apply branch only when `if` is true/false; unknown remains branch-unknown. |

Unsupported constructs produce `unsupported` condition traces and fail closed only
for the affected branch.

## 5. Iteration and Convergence

The engine cannot assume one-way execution because conditions may depend on
payload fields created by resolution.

Algorithm:

```text
seed requirement tree
for iteration in 1..MAX_ITERATIONS:
    resolve requirement paths
    render candidate payload
    evaluate conditions against candidate payload
    rebuild applicable requirement tree
    stop if required path set is unchanged
record non_converged finding if limit reached
```

Initial constants:

```text
MAX_ITERATIONS = 3
```

Non-convergence blocks V2 payload submission for the affected SKU and records:

- old required path set
- new required path set
- changed paths
- condition traces that introduced the changes

## 6. Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `requirement_models_v2.py` | Dataclass definitions and serialization helpers. |
| `schema_condition_evaluator_v2.py` | Evaluate supported JSON Schema conditions against candidate payload and emit traces. |
| `requirement_tree_builder_v2.py` | Build and iterate applicable requirement trees. |
| `evidence_resolver_v2.py` | Resolve path, derived, default, LLM, and review override values. |
| `llm_attribute_extractor_v2.py` | Extract child-path facts with evidence, enum/type lock, and null-on-absent behavior. |
| `confidence_scorer_v2.py` | Score child path resolutions using current evidence-grounded policy. |
| `review_adapter_v2.py` | Convert pending path decisions to/from existing review workflow. |
| `payload_composer_v2.py` | Render recursive resolution nodes into Amazon attributes. |
| `coverage_gate_v2.py` | Validate required tree coverage and review/default policy. |
| `listing_payload_engine_v2.py` | Orchestrate V2 analysis and emit `PayloadBuildPlan`. |

## 6.1 Schema Metadata Extraction

The initial metadata tree builder extracts enough schema shape data for generic
payload composition and path-level review:

- `list_value` nodes expose `value` enum constraints and inject
  `language_tag=en_US` when the schema declares the generic field.
- `measure` nodes expose required `value` / `unit` children and unit enums.
- `object` / `nested_object` nodes expose required non-generic children.
- schemas with explicit `selectors` are marked as `array_object` and retain the
  selector list for stable path-key generation.
- generic `language_tag` and `marketplace_id` are recorded as `auto_fields`
  instead of reviewable required children.

## 6.2 Evidence Resolution Contract

`evidence_resolver_v2.py` resolves RequirementTree paths into a recursive
ResolutionTree.

Initial supported source types:

- `path`: read from `AmazonListingDraft` using the same root names as the
  current resolver: `content`, `product`, `offer`, and `variation`.
- `default`: resolve fallback values and carry `safe_default` metadata.
- `review_override`: replay human/AI reviewed values by stable `path_key`.

Initial transform support mirrors the existing resolver for `text`, `integer`,
`boolean`, `boolean_yes_no`, `enum`, and `passthrough`.

Required unresolved leaf paths receive `MISSING_REQUIRED_ATTRIBUTE_RULE`.
Required low-confidence leaf paths receive `LOW_CONFIDENCE_REQUIRED_ATTRIBUTE`.
Required non-whitelisted defaults receive `UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE`.
Structural parent nodes with resolved children are not treated as low-confidence
facts by themselves; child paths carry the evidence and confidence.

LLM extraction and confidence scoring are intentionally deferred to S5/S6.

## 7. Integration Boundary

V2 integrates with `ProductListingAPIPlanBuilder` behind a mode switch:

```text
LISTING_PAYLOAD_ENGINE=v1     # current behavior
LISTING_PAYLOAD_ENGINE=shadow # run V1 for behavior, V2 for diff report
LISTING_PAYLOAD_ENGINE=v2     # use V2 output
```

Shadow mode:

- never calls PUT
- never changes the V1 submission decision
- writes `amazon_api_submissions` audit rows with
  `operation="listing_payload_v2_shadow"`
- stores V1 side context in `request_payload`:
  - `v1_status`
  - `v1_attribute_names`
  - `v1_attributes`
- stores V2 side context in `response_body`:
  - V2 attribute names and attributes
  - V2 required paths
  - V2 coverage findings
  - V2 condition traces
  - V2 pending review paths
  - summary counts and blocking codes

S12 first-pass scope:

- `ProductListingAPIPlanBuilder` invokes shadow mode for real SKUs when V1
  generates a plan or produces a pre-submit block with enough SKU context.
- The adapter records `shadow_built` or `shadow_failed`; failures are caught and
  logged so V1 behavior continues.
- Full V1/V2 diff presentation remains S13. S12 only persists enough audit
  material for S13 to compare old vs V2 required sets, payloads, coverage
  findings, review items, and strict-preview outcomes.

S13 first-pass scope:

- `ListingPayloadShadowDiffV2.report(product_type, sku, limit)` reads recent
  `listing_payload_v2_shadow` rows and returns stable dict summaries.
- The report compares V1/V2 attribute names and surfaces:
  - attributes only in V1
  - attributes only in V2
  - shared attributes
  - V2 missing required paths
  - V2 low-confidence required paths
  - V2 pending review paths
  - V2 finding/blocking codes
  - condition trace count
- CLI task: `report-listing-shadow-diff-v2 --product-type CHAIR --sku SKU1`
  (or `--category`) prints a read-only summary. `LISTING_V2_SHADOW_DIFF_LIMIT`
  controls row count, default 20.
- S13 still does not call PUT or Amazon preview. Strict-preview comparison is
  available through `validate-listing-v2`; multi-category regression evidence is
  deferred to S14.

S14 first-pass scope:

- `ListingPayloadV2Regression.evaluate(product_types, limit_per_category)` reads
  S13 diff summaries and returns `go` / `no_go` per category.
- Built-in live regression categories: `CABINET`, `HOME_MIRROR`, `OTTOMAN`.
  These require shadow evidence and no V2 blocking codes.
- Built-in exploratory categories: `CHAIR`, `SOFA`. These may have blocking
  results only when every blocking code is explainable:
  `MISSING_REQUIRED_ATTRIBUTE_RULE`, `LOW_CONFIDENCE_REQUIRED_ATTRIBUTE`,
  `NEEDS_REVIEW_REQUIRED_ATTRIBUTE`, or `UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE`.
- CLI task: `evaluate-listing-v2-regression` prints category go/no-go from
  stored shadow evidence. `LISTING_V2_REGRESSION_CATEGORIES` can override the
  default category list; `LISTING_V2_REGRESSION_LIMIT` controls rows per
  category.
- Evidence collection can now use `generate-listing-api --engine shadow`
  directly; `v2` remains blocked at the listing entrypoint until canary cutover.
- 2026-06-27 CABINET evidence hardening:
  - shadow SKU filter is case-insensitive;
  - diff CLI prints missing/pending/low-confidence path details;
  - `EvidenceResolverV2` can fall back to V2 candidate attributes and inherit
    scalar-list/list-of-dict child values;
  - `PayloadComposerV2` renders `array_object` scalar and scalar-list parent
    values generically;
  - `ListingPayloadEngineV2` candidate attributes include deterministic physical
    fields already supported by V1;
  - `CoverageGateV2` accepts rule-driven `coverage_ignore_required`.
  CABINET `meow251115FC0ie` latest shadow submission `114150` reports
  `missing=0`, `pending=0`, `blocking=0`; evidence report:
  `docs/test-reports/2026-06-27-listing-payload-v2-cabinet-shadow.md`.
- 2026-06-27 multi-category shadow regression:
  - regression evaluator evaluates the latest shadow row per SKU;
  - default regression returns `status=go total=5 go=5 no_go=0`;
  - CABINET / HOME_MIRROR / OTTOMAN live regression rows have no V2 missing,
    pending review, or blocking paths;
  - CHAIR / SOFA are exploratory `go` only, with explainable missing-rule /
    pending-review blockers;
  - SOFA `seat` now has explicit child rules for `depth`, `height`,
    `interior_width`, `fill_material`, and `material_type`.
  Evidence report:
  `docs/test-reports/2026-06-27-listing-payload-v2-shadow-regression.md`.
- 2026-06-27 authoritative dry-run canary:
  - `ProductListingAPIPlanBuilder` can run `LISTING_PAYLOAD_ENGINE=v2` as the
    authoritative dry-run path;
  - `--engine v2 --no-dry-run` remains blocked by CLI and service guardrails;
  - builder passes the already prepared draft into V2 so image, commercial, and
    variation decisions are preserved;
  - V2 merges schema-allowed deterministic candidate attributes after required
    tree composition, preventing non-required core fields such as
    `main_product_image_locator`, `purchasable_offer`,
    `fulfillment_availability`, and variation attributes from being dropped;
  - review-only V2 coverage blocks are persisted through `ReviewAdapterV2`
    using path-level review keys.
- 2026-06-27 strict-preview parity extension:
  - HOME_MIRROR V2 authoritative strict dry-run reached submitter and returned
    `skipped_existing`;
  - OTTOMAN V2 authoritative strict dry-run generated a new parent that passed
    Amazon `VALIDATION_PREVIEW` with 0 issues;
  - RequirementTreeBuilderV2 ignores stale expanded `required_properties` and
    derives V2 required paths from raw schema plus evaluated condition branches;
  - variation parent semantics are normalized so `parentage_level=parent` does
    not require `child_parent_sku_relationship`.
- Cutover/retirement plan:
  `docs/retirement/listing-payload-engine-v2-cutover-2026-06-27.md`.
- This evaluator is intentionally read-only: it does not call Amazon, does not
  submit PUT, and does not switch `LISTING_PAYLOAD_ENGINE=v2`.

## 8. Review Compatibility

V2 review items use path-level keys:

```json
{
  "path_key": "seat.material_type",
  "attribute": "seat",
  "display_label": "Seat Material",
  "value": "linen",
  "evidence": "matte linen cushion",
  "confidence_score": 65,
  "route": "auto_approved",
  "path_key_version": "v2_path_keys_2026_06"
}
```

Rules:

- Parent object nodes are not approved unless all required children are approved
  or safely covered.
- AI review can approve text and enum child paths when evidence is grounded.
- Measure paths require explicit numeric evidence and unit evidence.
- Unsupported or selector-unstable paths route to human or fail closed.

## 9. Coverage Compatibility

Tree-level coverage blocks:

- missing required top-level paths
- missing required children
- measure without both `value` and `unit`
- list value without `value`
- enum value outside schema enum

The V2 gate emits path-level findings and reuses current blocking code names
where the business meaning is the same:

- `MISSING_REQUIRED_ATTRIBUTE_RULE`
- `LOW_CONFIDENCE_REQUIRED_ATTRIBUTE`
- `NEEDS_REVIEW_REQUIRED_ATTRIBUTE`
- `UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE`

Coverage output maps directly back into `PayloadBuildPlan`:

- `covered_required_paths`
- `missing_required_paths`
- `low_confidence_required_paths`
- `pending_review_paths`
- `safe_default_paths`
- `findings`

## 10. Payload Composition Contract

`payload_composer_v2.py` is a pure renderer. It does not resolve values, score
confidence, route review, or decide coverage. Those decisions stay in
ResolutionTree and the later coverage gate.

Initial supported rendering rules:

- top-level `list_value` renders as `[{auto_fields..., "value": scalar}]`.
- `measure` renders a single object with `value` and `unit`, sourced from either
  the parent resolution dict or child resolution nodes.
- `object` / `nested_object` renders recursive child payloads under the parent
  object.
- `array_object` renders the same recursive object shape while preserving
  selector-related `auto_fields`, such as `marketplace_id`.
- blocking resolution nodes are omitted from payload composition; later coverage
  decides whether the omission blocks submission.
- pending review required paths
- unsafe default required paths
- non-converged condition evaluation
- unsupported required branch with no safe fallback

The V2 coverage result must be convertible to the current pre-submit result shape
so the rest of the plan builder can continue to aggregate status counts.

## 10. Phase 1 Read-only CLI Contract

The first implementation should expose a read-only command before any production
behavior changes:

```bash
python3 main.py --task analyze-listing-requirements-v2 --category CHAIR --sku meow2511081Gqqd
```

Output must include:

- applicable required paths
- non-applicable conditional required paths that were considered
- unknown/unsupported conditions
- object required children
- condition traces
- stable path keys
- whether the tree converged

The command must not call PUT. It should not call Amazon APIs unless strict
schema refresh is explicitly requested.

## 11. Test Plan

Unit tests:

- condition evaluator truth table
- stable path key generation
- RequirementTree extraction from synthetic schemas
- CHAIR cached-schema golden for single listing context
- object/measure payload composer golden
- tree-level coverage gate
- path-level confidence scoring
- review override replay by path

Integration tests:

- V2 shadow mode for CHAIR single SKU
- V2 strict-preview dry-run path without PUT
- CABINET/HOME_MIRROR/OTTOMAN regression comparison before cutover

## 12. Open Questions

1. ~~Should V2 path-level review decisions reuse `amz_listing_pending_review` JSON
   columns only, or add a V2-specific review table for queryability?~~
   **已决策 (2026-06-26)**：新建 V2 path-level 表 `amz_listing_pending_review_v2`，一行 = 一个 path-level review item，`UNIQUE (category, sku, path_key, path_key_version)` 保证 resume replay 幂等。V1 表保持不变，cutover 后 `@retire`。详见 `docs/decisions/ADR-2026-06-26-v2-review-persistence.md`。S7 启动时创建 migration / repository / `review_adapter_v2.py`。
2. Should learned-required feedback be stored with condition trace metadata in a
   new table, or attached to `amazon_api_submissions` response analysis?
3. Which existing CLI should display V2 shadow reports: a new command only, or
   `generate-listing-api` with a flag?
