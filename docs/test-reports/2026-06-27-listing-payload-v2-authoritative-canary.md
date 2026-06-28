# Listing Payload Engine V2 Authoritative Canary - 2026-06-27

## Scope

Validate the first authoritative dry-run path for
`LISTING_PAYLOAD_ENGINE=v2`.

This path lets V2 attributes and V2 coverage replace the V1
resolver/renderer/coverage inside `ProductListingAPIPlanBuilder`, while still
blocking LIVE PUT. Commands used `--strict-validation`, so Amazon calls were
`VALIDATION_PREVIEW` or read-only existing-listing checks.

## Guardrails

- `generate-listing-api --engine v2` is allowed only when `dry_run=True`.
- `--engine v2 --no-dry-run` is blocked by both CLI and service guardrails with
  `v2_engine_requires_dry_run`.
- V2 builder receives the already prepared draft, preserving upstream commercial
  gate, image selection, and variation decisions.

## Evidence

| Product type | Command scope | Result |
| --- | --- | --- |
| CABINET | `meow251115FC0ie` | V2 authoritative path reached submitter; result `skipped_existing`; no PUT. A first run exposed `MISSING_MAIN_IMAGE`, fixed by merging schema-allowed deterministic candidate attributes. |
| HOME_MIRROR | `meow251108CqW5i` | V2 authoritative path reached submitter; result `skipped_existing`; no PUT. |
| OTTOMAN | `meow2511088jSUW`, `meow260518LZZCw` | V2 authoritative path generated 3 plans. New parent `PARENT-818700D0BEB9` returned `validation_preview_passed` with 0 issues; both children returned `skipped_existing`; no PUT. |

## Fixes Included

- `RequirementTreeBuilderV2` no longer uses cached/expanded
  `required_properties` as the V2 tree seed. It now derives requirements from
  raw schema `required` plus dynamically evaluated condition branches.
- Added a generic Amazon variation context filter: when
  `parentage_level=parent`, `child_parent_sku_relationship` is not treated as
  required for the parent listing. Child listings still require the relationship
  when the schema condition applies.
- V2 payload composition now merges schema-allowed deterministic candidate
  attributes after required-tree composition. This preserves non-required but
  operationally required fields such as:
  - `main_product_image_locator`
  - `other_product_image_locator_*`
  - `purchasable_offer`
  - `fulfillment_availability`
  - variation attributes
- `purchasable_offer` now includes `marketplace_id`, matching V1 payload shape.

## Verification

```bash
.venv/bin/pytest tests/unit/cli/test_listing_handlers.py \
  tests/unit/cli/test_task_dispatcher.py \
  tests/unit/cli/test_operation_handlers.py \
  tests/integration/cli/test_main_non_interactive_entrypoint.py \
  tests/unit/services/test_product_listing_service.py \
  tests/unit/services/test_product_listing_api_plan_builder.py \
  tests/unit/services/test_requirement_tree_builder_v2.py \
  tests/unit/services/test_schema_condition_evaluator_v2.py \
  tests/unit/services/test_listing_payload_shadow_adapter_v2.py \
  tests/unit/services/test_listing_payload_shadow_diff_v2.py \
  tests/unit/services/test_listing_payload_v2_regression.py \
  tests/unit/services/test_listing_payload_engine_v2.py \
  tests/unit/services/test_evidence_resolver_v2.py \
  tests/unit/services/test_confidence_scorer_v2.py \
  tests/unit/services/test_review_adapter_v2.py \
  tests/unit/services/test_coverage_gate_v2.py \
  tests/unit/services/test_payload_composer_v2.py \
  tests/integration/repositories/test_amazon_api_submission_repository_sql_contract.py
```

Result: `167 passed`.

Ruff passed for changed V2/builder/CLI/test files. `git diff --check` passed.

## Remaining Gate

- V2 LIVE PUT remains disabled.
- Need one path-level review resume smoke on V2 authoritative plans:
  pending review -> approval -> override replay.
- Need broader non-existing SKU coverage beyond the generated OTTOMAN parent
  before enabling any LIVE canary.

## Next Agent Handoff

Recommended next task: run a V2 path-level review resume smoke.

Goal:

1. Produce or select a V2 authoritative plan with
   `NEEDS_REVIEW_REQUIRED_ATTRIBUTE`.
2. Persist the pending path-level review row through `ReviewAdapterV2`.
3. Run review approval.
4. Rebuild the V2 plan with approved overrides and confirm the same path is no
   longer blocking.

Useful starting points:

```bash
# Exploratory category with known pending-review behavior.
python main.py --task generate-listing-api \
  --category SOFA \
  --sku meow251108Bg4d4 \
  --strict-validation \
  --engine v2

# Review V2 pending paths.
python main.py --task review-pending-attributes \
  --category SOFA \
  --engine v2

# Submit reviewed V2 paths in dry-run mode only.
python main.py --task submit-reviewed-plans \
  --category SOFA \
  --engine v2
```

Production-like evidence should be collected with the same workspace-mounted
Docker command pattern used in this report, so the current unbuilt source runs
against the production env and Docker `proxy` network.

Acceptance for the next slice:

- At least one row exists in `amz_listing_pending_review_v2`.
- AI or human decision changes the row from pending to completed, or records an
  explicit human-required state.
- Rebuilding the same SKU with approved V2 overrides removes the review-only
  block.
- `--engine v2 --no-dry-run` remains blocked.
- Targeted tests and `git diff --check` pass.

Do not:

- Enable LIVE `--engine v2`.
- Add `@retire` markers to V1 resolver/renderer/coverage before V2 review resume
  and LIVE canary evidence are complete.
- Treat CHAIR/SOFA exploratory `go` as LIVE readiness; they are still allowed to
  have explainable missing/pending paths.
