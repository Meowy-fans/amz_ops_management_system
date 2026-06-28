# EPIC: Listing Requirement & Payload Engine V2

> Epic ID: `EPIC-AMZ-LISTING-REQUIREMENT-PAYLOAD-V2`
> Status: In Progress
> Date: 2026-06-26
> Owner: amz-listing-management-system
> Predecessors:
> - `EPIC-AMZ-LISTING-API-NATIVE-QUALITY` (Completed 2026-06-15)
> - `EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES` (Completed 2026-06-15)
> - `TASK-144 Confidence Review Pipeline` (Completed 2026-06-25)

## Current Progress

Updated: 2026-06-27 by Codex (S14 regression evaluator + cutover plan first pass).

Overall production replacement progress: **50% - 55%**.

Read-only / shadow-plan foundation progress: **about 95%**.

Current status:

- V2 remains **read-only** and does not change current `generate-listing-api`,
  coverage gate, submitter, or LIVE behavior.
- S0-S14 tooling/planning have first-pass implementation; S14 real
  multi-category shadow/strict-preview evidence is still pending.
- S5/S6/S7 are now wired through `ListingPayloadEngineV2.build_read_only_plan()`:
  LLM extraction feeds `EvidenceResolverV2`, `ConfidenceScorerV2` scores the
  `ResolutionTree`, and required LLM leaf routes become path-level pending
  review state for coverage and review persistence.
- S12 shadow mode is wired behind `LISTING_PAYLOAD_ENGINE=shadow`; V1 still owns
  behavior and V2 writes `listing_payload_v2_shadow` audit rows to
  `amazon_api_submissions`.
- S13 diff tooling reads those shadow rows and reports V1/V2 attribute deltas,
  V2 required coverage gaps, pending review paths, condition trace counts, and
  blocking codes through `report-listing-shadow-diff-v2`.
- S14 regression evaluator consumes shadow diff summaries and returns category
  go/no-go decisions through `evaluate-listing-v2-regression`; CABINET has one
  latest-row shadow `go` evidence item, while HOME_MIRROR / OTTOMAN / CHAIR /
  SOFA evidence remains pending. Cutover/retirement plan is documented but no
  old module is retired until parity is proven.
- CABINET shadow parity fixes completed on 2026-06-27: case-insensitive SKU
  shadow lookup, path detail printing in diff reports, `array_object` scalar/list
  scalar rendering, candidate attribute fallback, list-of-dict child inheritance,
  deterministic physical candidate fields, and rule-driven
  `coverage_ignore_required`.
- `ListingPayloadEngineV2.build_read_only_plan()` can already produce a
  `PayloadBuildPlan` by chaining:

  ```text
  RequirementTree
    -> ResolutionTree
    -> confidence_scorer_v2
    -> payload_composer_v2
    -> coverage_gate_v2
    -> PayloadBuildPlan
  ```

Implemented modules:

- `requirement_models_v2.py`
- `schema_condition_evaluator_v2.py`
- `requirement_tree_builder_v2.py`
- `evidence_resolver_v2.py`
- `payload_composer_v2.py`
- `coverage_gate_v2.py`
- `confidence_scorer_v2.py`
- `review_adapter_v2.py`
- `amazon_listing_pending_review_v2_repository.py`
- `validation_preview_v2.py`
- `feedback_learning_adapter_v2.py`
- `amazon_listing_learned_required_paths_v2_repository.py`
- `listing_payload_shadow_adapter_v2.py`
- `listing_payload_shadow_diff_v2.py`
- `listing_payload_v2_regression.py`
- `listing_payload_engine_v2.py`

Implemented CLI:

- `analyze-listing-requirements-v2` for read-only requirement analysis.
- `validate-listing-v2` for Amazon VALIDATION_PREVIEW without PUT.
- `learn-required-from-submissions` for V2 feedback learning from Amazon 90220.
- `report-listing-shadow-diff-v2` for read-only V1/V2 shadow diff summaries.
- `evaluate-listing-v2-regression` for S14 category go/no-go evaluation from
  shadow evidence.
- `review-pending-attributes --engine v2` and `submit-reviewed-plans --engine v2`
  for V2 path-level review.

Current verification:

```text
871 passed
S5/S6/S7 wiring fix targeted tests: 35 passed
S12 shadow adapter targeted tests: 8 passed
S13 shadow diff targeted tests: 34 passed
S14 regression evaluator targeted tests: 29 passed
ruff: All checks passed
```

Completed first-pass slices:

| Slice | Status | Notes |
| --- | --- | --- |
| S0 | First pass complete | ADR, Epic, module design, stable path-key and convergence contract documented. |
| S1 | First pass complete | Conservative JSON Schema condition evaluator with unsupported-condition reporting. |
| S2 | First pass complete | Applicable RequirementTree builder with conditional required trace output. |
| S3 | First pass complete | Schema metadata extraction for list value, measure, object, auto fields, and selectors. |
| S4 | First pass complete | Path/default/review-override evidence resolver; LLM source deferred to S5. |
| S5 | First pass complete | Path-level LLM extraction with enum lock, null-on-absent, evidence-bound, confidence cap. |
| S6 | First pass complete | Path-level confidence scoring with parent aggregation and evidence-grounded signals. |
| S7 | First pass complete | V2 path-level review persistence and adapter; CLI `--engine v1\|v2` flag wired. |
| S8 | First pass complete | Generic payload composer for list value, measure, object, nested object, and array object. |
| S9 | First pass complete | Tree-level coverage gate for required children, measure value/unit, review, confidence, and safe default policy. |
| S10 | First pass complete | Amazon VALIDATION_PREVIEW integration with audit persistence and V2 coverage comparison. |
| S11 | First pass complete | V2 feedback learning from Amazon 90220 at path_key granularity; tree builder hook + CLI task. |
| S12 | First pass complete | `ProductListingAPIPlanBuilder` can run V2 shadow audits beside V1 through `LISTING_PAYLOAD_ENGINE=shadow`; no PUT and no V1 decision changes. |
| S13 | First pass complete | CLI/service can report V1/V2 attribute deltas, V2 findings, pending review, condition trace counts, and blocking summaries from shadow audit rows. |
| S14 | Tooling/planning first pass complete | Regression evaluator and cutover/retirement plan are in place; real CABINET/HOME_MIRROR/OTTOMAN/CHAIR/SOFA evidence collection remains pending. |

Not yet implemented:

- Real multi-category shadow/strict-preview evidence collection
- `LISTING_PAYLOAD_ENGINE=v2` replacement implementation and canary cutover

## 1. Background

The current API-native listing pipeline can create and validate listings through
Amazon SP-API, but its attribute pipeline is still mostly flat:

1. Required attributes are resolved as a product-type-level list.
2. Conditional schema requirements are not evaluated against the current listing
   payload.
3. Object attributes such as `frame`, `seat`, and `item_depth_width_height` are
   treated as single top-level fields, not as recursive schema trees with required
   children.
4. Confidence scoring and pending review operate at top-level attribute granularity.

This limits new product type onboarding. For CHAIR, production evidence shows:

- `AmazonSchemaService.get_expanded_required_properties("CHAIR")` returns only
  the top-level required list.
- `frame`, `seat`, and `item_depth_width_height` enter coverage only through
  preview-learned required feedback, and only as flat top-level names.
- Required object children such as `frame.material` are ignored by coverage: the
  gate's `_has_payload_value` only checks that the top-level `frame` payload is
  non-empty, so a `frame` object missing its required `material` child still
  passes. `_collect_direct_required_property_names` reads only top-level
  `required` and unconditional `allOf[].required`, never `then.required`, so
  conditional required children are never evaluated against the payload.
- Static collection of all `then.required` fields would over-block badly: CHAIR
  expands to many conditionally required offer, hazmat, battery, package, and
  variation attributes that are not applicable to every listing.

The conclusion is that a durable solution requires a new tree-shaped requirement
and payload engine, not more patches on the existing flat resolver.

## 2. Epic Goal

Build a production-grade V2 engine that can replace the current listing attribute
resolution, payload rendering, coverage gate, and review-routing modules while
preserving the current business safety mechanisms:

- schema-driven requirements
- conditional required evaluation
- object and nested object payload generation
- evidence-grounded confidence scoring
- safe-default whitelist
- AI/human review routing
- pending review persistence and resume
- strict dry-run `VALIDATION_PREVIEW`
- fail-closed behavior for uncertain required facts

The V2 engine must be able to explain and build Amazon Listings Items API payloads
from a recursive schema tree, then integrate back into the current
`generate-listing-api` orchestration.

## 3. Non-goals

- Replace commercial gate, variation resolver, image selector, quality gate, or
  Amazon submitter in this Epic.
- Build a new web UI for manual review.
- Change the default safety posture: dry-run remains default and LIVE requires
  explicit `--no-dry-run`.
- Use LLM output as an unreviewed fact source for required attributes.
- Hardcode CHAIR-specific object payload logic in Python.

## 4. Core Design

V2 introduces explicit intermediate products:

```text
Amazon schema + current listing context
  -> RequirementTree
  -> ResolutionTree
  -> PayloadBuildPlan
  -> Listings Items API attributes payload
  -> local tree-level coverage
  -> strict validation preview / submitter
```

### 4.1 RequirementTree

`RequirementTree` is the current listing scenario's applicable schema tree.

It records:

- top-level attribute name
- shape: `list_value`, `measure`, `object`, `nested_object`, `array_object`, etc.
- whether the node is required for this payload
- required children
- enum and unit constraints
- automatic fields such as `language_tag` and `marketplace_id`
- condition path and reason
- whether the condition was evaluated, unknown, or intentionally fail-closed

The key requirement is dynamic conditional evaluation. V2 must not statically add
every `if/then/else.required` field to every listing.

### 4.1.1 Conditional Evaluation Order

Amazon schema conditions can depend on attributes that are themselves produced by
the payload engine. V2 must therefore define an explicit convergence strategy
instead of assuming a one-pass linear flow.

Default strategy:

1. Build an initial requirement tree from always-required fields and conditions
   that can be evaluated from draft context or already-present structural payload
   fields.
2. Resolve values for known required and recommended paths.
3. Re-evaluate conditional requirements against the newly rendered candidate
   payload.
4. Add newly applicable requirements and resolve them.
5. Repeat until the applicable requirement set is stable, or until a configured
   iteration limit is reached.

Required guardrails:

- The iteration limit must be small and explicit, with an audit finding when
  convergence is not reached.
- Unknown or unsupported condition shapes must be reported with condition path
  and reason. They must not silently become global required fields.
- Unknown conditions fail closed only for the affected conditional branch, not by
  exploding every `then.required` field into the product-type-wide required set.
- The engine must persist enough condition trace data to explain why a path is
  required, not required, or unknown.

### 4.2 ResolutionTree

`ResolutionTree` is the value/evidence state for every applicable requirement
path.

Example paths:

```text
frame.color
frame.material
seat.height
seat.material_type
item_depth_width_height.depth
maximum_weight_recommendation.value
maximum_weight_recommendation.unit
```

Each node records:

- value
- source: `path`, `derived`, `llm`, `default`, `review_override`
- evidence
- confidence label and confidence score
- review status
- safe-default status
- blocking status and reason
- child findings

### 4.2.1 Stable Path Keys

Review resume depends on stable path keys. V2 must not use volatile Python list
indexes or incidental traversal order as review identifiers.

Path key requirements:

- Object children use dot paths, such as `frame.color` or `seat.material_type`.
- Array object entries use selector-derived keys when the schema defines
  selectors, for example `frame{marketplace_id=ATVPDKIKX0DER}.color`.
- If a schema lacks a stable selector, V2 must derive a deterministic identity
  from schema path plus normalized value fingerprint, or mark the node as
  non-resumable and route it to fail-closed review.
- Review decisions and overrides must target the stable path key and must be
  reapplied without rerunning LLM extraction.
- Any path-key migration must be versioned in `PayloadBuildPlan` audit metadata.

### 4.3 PayloadBuildPlan

`PayloadBuildPlan` is the bridge back to the existing listing orchestration.

It contains:

- final Amazon `attributes` payload
- full `RequirementTree`
- full `ResolutionTree`
- covered required paths
- missing required paths
- low-confidence required paths
- pending review paths
- safe-default paths
- dropped or inapplicable attributes
- audit metadata suitable for `amazon_api_submissions` and pending review

## 5. Compatibility Requirements

V2 is intended to replace existing modules, so it must preserve business behavior,
not simplify it.

| Current capability | V2 requirement |
| --- | --- |
| `AttributeResolver` evidence/confidence | V2 records evidence/confidence at node path level. |
| `ConfidenceScorer` | V2 scores child paths and aggregates to parent nodes. |
| `ReviewManager` pending lifecycle | V2 persists review items with stable path keys and supports resume without rerunning LLM. |
| `AttributeReviewAgent` | V2 verifies evidence-bound values for path-level items. |
| Safe default whitelist | V2 only permits defaults explicitly marked safe for the exact path. |
| Sensitive markers | V2 blocks LLM/default handling for identifiers, compliance, certification, hazmat, and other sensitive paths unless explicitly approved. |
| Coverage gate | V2 validates top-level required and required children, not just non-empty parent payload. |
| Strict dry-run | V2 supports `VALIDATION_PREVIEW` without PUT and persists feedback. |
| Learned required feedback | V2 can consume feedback but must avoid unconditional product-type-wide overblocking when feedback is conditional. |
| Existing live categories | CABINET, HOME_MIRROR, and OTTOMAN must pass regression before cutover. |

## 6. Proposed Module Boundary

New modules should live beside existing services until cutover:

| Module | Responsibility |
| --- | --- |
| `schema_condition_evaluator_v2.py` | Evaluate a conservative supported subset of Amazon JSON Schema conditions against the current payload/context. |
| `requirement_tree_builder_v2.py` | Build the applicable `RequirementTree` from Product Type schema and current listing context. |
| `requirement_models_v2.py` | Dataclasses / typed contracts for `RequirementNode`, `ResolutionNode`, and `PayloadBuildPlan`. |
| `evidence_resolver_v2.py` | Resolve path/derived/default/LLM/review values for requirement paths. |
| `llm_attribute_extractor_v2.py` | Evidence-bound child-path extraction with enum/unit/type constraints. |
| `confidence_scorer_v2.py` | Path-level confidence scoring compatible with current scoring policy. |
| `review_adapter_v2.py` | Persist and resume path-level pending reviews through the current review workflow. |
| `payload_composer_v2.py` | Render recursive schema nodes into Listings Items API payload shape. |
| `coverage_gate_v2.py` | Validate tree-level required coverage and review/default policy. |
| `listing_payload_engine_v2.py` | Orchestrate requirement analysis, resolution, rendering, coverage, and audit output. |

Existing modules remain active until V2 strict-preview regressions prove parity.

## 7. Work Breakdown

| Slice | Title | Status | Estimate | Acceptance |
| --- | --- | --- | ---: | --- |
| S0 | V2 contracts, ADR, module design | First pass complete | 2-3 days | `RequirementTree`, `ResolutionTree`, `PayloadBuildPlan`, condition iteration/convergence, stable path keys, and cutover contract are documented and reviewed. |
| S1 | Schema condition evaluator | First pass complete | 4-6 days | Unit tests cover `if/then/else`, `allOf`, `anyOf`, `oneOf`, `not`, `required`, `contains`, enum/const basics, and unknown-condition fail-closed behavior. |
| S2 | RequirementTree builder | First pass complete | 3-5 days | CHAIR single listing explains why `frame`, `seat`, and `item_depth_width_height` apply and why `frame_material` does not apply in that context. |
| S3 | Schema metadata tree | First pass complete | 3-4 days | Object, measure, list value, language tag, marketplace ID, enum, and required-child metadata are extracted from cached schemas. |
| S4 | Evidence resolver V2 | First pass complete, LLM deferred | 4-6 days | Path, derived, default, review override, and LLM source attempts produce path-level resolution nodes with evidence and state. |
| S5 | LLM child-path extraction | First pass complete | 4-6 days | LLM extraction is enum/type constrained, returns null when evidence is absent, and records source quotes for path-level scoring. |
| S6 | Confidence scorer V2 | First pass complete | 3-5 days | Existing evidence-grounded policy works for child paths; parent nodes aggregate child review state conservatively. |
| S7 | Review workflow adapter | First pass complete | 4-6 days | `review-pending-attributes` and `submit-reviewed-plans` can handle path-level review keys without losing resume determinism. |
| S8 | Generic payload composer | First pass complete | 5-7 days | Golden payloads render valid object, nested object, list value, measure, `language_tag`, and `marketplace_id` shapes. |
| S9 | Tree-level coverage gate | First pass complete | 4-6 days | Parent objects with missing required children fail locally; complete required children pass; unsafe defaults and pending reviews block. |
| S10 | Strict validation preview integration | First pass complete | 2-3 days | V2 plans can run Amazon `VALIDATION_PREVIEW` without PUT and persist comparable audit results. |
| S11 | Feedback learning adapter | First pass complete | 2-4 days | Amazon missing-required feedback can be associated with schema path/context without blindly forcing every listing in a product type. |
| S12 | Plan builder integration adapter | First pass complete | 3-5 days | `ProductListingAPIPlanBuilder` can run V2 in shadow mode beside the existing pipeline. |
| S13 | Shadow reports and diff tooling | First pass complete | 2-3 days | CLI can compare old vs V2 requirement, payload, coverage, and validation outcomes for selected SKUs. |
| S14 | Regression and cutover | Authoritative dry-run canary first pass complete; LIVE replacement not started | 9-13 days | CABINET, HOME_MIRROR, and OTTOMAN strict-preview regressions remain green; CHAIR/SOFA dry-run categories produce explainable V2 failures or preview passes. |

Expected module work: **54-84 person-days**.

Expected single-developer / single-agent calendar time: **36-55 working days**,
assuming implementation, testing, and fixes are interleaved.

## 8. Implementation Phases

### Phase 1: Read-only Intelligence

Deliver S0-S3.

Status: **First pass complete**.

No production behavior changes.

Acceptance:

1. V2 can print the applicable required tree for CHAIR `meow2511081Gqqd`.
2. It does not statically explode CHAIR into all conditional offer/hazmat/battery
   required fields.
3. It can explain condition matches and non-matches.
4. The ADR defines condition evaluation iteration order, convergence limit, and
   unknown-condition fail-closed scope.
5. The module design defines stable path-key rules for object arrays, selectors,
   review decisions, and override replay.

### Phase 2: Resolution and Review Semantics

Deliver S4-S7.

Status: **First pass complete** for resolver, LLM extraction, confidence scoring,
and path-level review adapter.

Still no submitter integration.

Acceptance:

1. Path-level resolution nodes preserve source, evidence, confidence, score, and
   review status.
2. Review overrides can be applied by path without rerunning LLM.
3. Sensitive paths and unsafe defaults remain fail-closed.

### Phase 3: Payload and Coverage

Deliver S8-S9.

Status: **First pass complete** for standalone composer and coverage gate.

Acceptance:

1. Generic object and measure payload rendering is verified by golden tests.
2. Tree-level coverage catches missing child requirements.
3. A non-empty parent object does not bypass missing required children.

### Phase 4: Shadow Integration

Deliver S10-S13.

Status: **First pass complete** for strict-preview integration, shadow audit,
and shadow diff reporting. Multi-category shadow evidence collection remains
part of S14.

Acceptance:

1. `generate-listing-api` can run V2 in shadow mode for selected SKUs.
2. Shadow audits persist V1 payload/status and V2 plan summaries without changing
   V1 submission decisions.
3. Shadow reports compare old and V2 required sets, payloads, coverage findings,
   review items, and strict-preview results.
4. Shadow mode never calls PUT.

### Phase 5: Replacement

Deliver S14.

Status: **Shadow regression and authoritative dry-run canary first pass complete;
LIVE replacement not started**.
`evaluate-listing-v2-regression` can evaluate shadow evidence and
`docs/retirement/listing-payload-engine-v2-cutover-2026-06-27.md` defines the
cutover/retirement gate. Default five-category regression now returns
`status=go total=5 go=5 no_go=0`.

Live regression evidence:

- CABINET `meow251115FC0ie` latest shadow submission `114150`: V2
  `missing=0`, `pending=0`, `blocking=0`.
- HOME_MIRROR `meow251108CqW5i` latest shadow submission `115998`: V2
  `missing=0`, `pending=0`, `blocking=0`.
- OTTOMAN `meow2511088jSUW` / `meow260518LZZCw` latest shadow submissions
  `116003` / `116002`: both V2 `missing=0`, `pending=0`, `blocking=0`; V1
  parent strict preview passed and children were skipped existing.

Exploratory evidence:

- CHAIR `meow2511081Gqqd` remains `go` because blocking is explainable as
  missing rules / pending review.
- SOFA `meow251108Bg4d4` stored shadow row remains exploratory `go`; after the
  SOFA `seat` rule fix, direct V2 read-only plan has `missing=0` and only
  `seating_capacity.value` / `sofa_type.value` pending review.

Detailed report:
`docs/test-reports/2026-06-27-listing-payload-v2-shadow-regression.md`.

Authoritative dry-run canary:

- `generate-listing-api --engine v2` is now allowed only for dry-run /
  strict-validation. LIVE `--no-dry-run` remains blocked at both CLI and service
  layers.
- `ProductListingAPIPlanBuilder` V2 mode uses
  `ListingPayloadEngineV2.build_read_only_plan_from_draft()` so upstream
  commercial, image, and variation decisions are preserved.
- V2 attributes and V2 coverage replace the V1 resolver/renderer/coverage for
  this dry-run path.
- V2 payload composition merges schema-allowed deterministic candidate
  attributes that are not part of the required tree, such as images, offers,
  fulfillment, and variation attributes.
- CABINET `meow251115FC0ie` strict dry-run canary with `--engine v2` entered the
  V2 authoritative submitter path and returned `skipped_existing`; no PUT was
  executed.
- HOME_MIRROR `meow251108CqW5i` strict dry-run canary returned
  `skipped_existing`; no PUT was executed.
- OTTOMAN family strict dry-run canary generated 3 plans. New parent
  `PARENT-818700D0BEB9` returned `validation_preview_passed` with 0 issues;
  both existing children were skipped; no PUT was executed.
- V2 no longer seeds RequirementTree from cached expanded `required_properties`;
  requirements come from raw schema `required` plus evaluated conditional
  branches. A generic variation parent filter prevents
  `child_parent_sku_relationship` from blocking parent listings while preserving
  child-listing requirements.

Next handoff:

- Next slice should focus on V2 path-level review resume:
  `pending review -> approval -> override replay`.
- Recommended exploratory seed: SOFA `meow251108Bg4d4`, because the current V2
  plan can produce pending review paths such as `seating_capacity.value` and
  `sofa_type.value`.
- Keep `--engine v2 --no-dry-run` blocked until review resume and at least one
  LIVE canary readiness review are complete.
- Do not add `@retire` markers to V1 resolver/renderer/coverage yet.

Acceptance:

1. CABINET, HOME_MIRROR, and OTTOMAN strict-preview regressions remain green.
2. CHAIR and SOFA failures are explainable as missing evidence, review-pending
   paths, unsafe defaults, or true schema requirements.
3. Existing flat resolver/renderer/coverage modules are marked with `@retire`
   only after V2 parity is proven.

## 9. Acceptance Criteria

The Epic is complete only when all criteria below are true:

1. V2 evaluates Amazon conditional required fields against the current listing
   context instead of statically merging all `then.required` fields.
2. V2 represents requirements and resolutions as trees with stable path keys.
3. V2 has a deterministic condition evaluation convergence strategy with an
   explicit iteration limit and auditable unknown-condition handling.
4. V2 supports object, nested object, list value, measure, enum, language tag,
   marketplace ID, and selector-aware payload rendering.
5. Required object children are validated locally.
6. Confidence scoring works at child path level and aggregates conservatively.
7. Pending review lifecycle supports path-level items and deterministic resume.
8. Safe defaults only pass when explicitly whitelisted for the path.
9. LLM extraction remains evidence-bound, enum/type constrained, and capped by
   current confidence policy.
10. Strict dry-run `VALIDATION_PREVIEW` works for V2 and persists feedback.
11. Existing live-eligible categories do not regress under strict preview.
12. V2 can replace the current resolver/renderer/coverage gate in
    `generate-listing-api`.
13. Old modules are retired through a documented retirement plan, not deleted
    abruptly.
14. Targeted tests, integration tests, and full regression pass.
15. `STATUS.md`, `TODO.md`, module design docs, and acceptance reports are updated.

## 10. Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Amazon schema condition support is incomplete. | High | Implement a conservative supported subset; unknown condition state fails closed and is visible in reports. |
| Conditional requirements and resolved values have cyclic dependencies. | High | Define an explicit iterative evaluation order, convergence limit, and non-convergence audit finding in S0. |
| Review path keys are unstable for array objects. | High | Define selector-based or fingerprint-based stable path keys in S0; mark non-resumable paths fail-closed. |
| Static learned-required feedback causes overblocking. | High | Add condition/context metadata to V2 feedback learning before using it as hard required. |
| Object renderer creates invalid Amazon payload shape. | High | Golden tests from cached schemas plus strict-preview smoke before any LIVE cutover. |
| Child-path review breaks existing pending review workflow. | High | Build a review adapter and keep old review path active until V2 parity is proven. |
| LLM invents child values. | High | Evidence quote requirement, context matching, enum/type lock, confidence cap, and review routing. |
| Existing live categories regress. | High | Shadow mode first; cut over only after CABINET/HOME_MIRROR/OTTOMAN strict-preview acceptance. |
| V2 becomes a parallel permanent system. | Medium | Define cutover and `@retire` plan from the start. |

## 11. Rollback / Safety

- V2 starts read-only, then shadow-only, then strict-preview-only.
- LIVE submission stays on the existing path until parity is proven.
- No existing production tables are dropped.
- New persistence, if needed, must be additive.
- Feature flag controls V2 activation:

```text
LISTING_PAYLOAD_ENGINE=v1|v2|shadow
```

- Any Amazon write remains behind current `--no-dry-run` and submitter checks.
- Amazon SP-API traffic continues to require the configured fixed egress proxy.

## 12. Related Documents

- `docs/proposals/schema-conditional-required-fix.md`
- `docs/proposals/confidence-based-review-pipeline.md`
- `docs/proposals/confidence-review-pipeline-dev-plan.md`
- `docs/epics/api-native-listing-quality-pipeline.md`
- `docs/epics/schema-driven-attribute-resolution.md`
- `docs/api-native-listing-system-design.md`
- `docs/module-design/api-attribute-resolution.md`
- `docs/test-reports/2026-06-25-confidence-review-pipeline-dev.md`
