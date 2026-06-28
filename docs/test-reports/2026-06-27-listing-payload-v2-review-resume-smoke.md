# Listing Payload Engine V2 Review Resume Smoke - 2026-06-27

## Scope

Validate V2 path-level review resume on the authoritative dry-run path:

```text
generate-listing-api --engine v2
  -> pending review persistence
  -> review-pending-attributes --engine v2 --approve-human
  -> submit-reviewed-plans --engine v2
  -> generate-listing-api --engine v2 (override replay)
```

No LIVE PUT was executed.

## Prerequisites Applied

- Production DB migrated to alembic `012_amz_listing_learned_required_paths_v2`
- `amz_listing_pending_review_v2` table created
- `alembic_version.version_num` widened to `VARCHAR(64)` because revision ids
  `011_amz_listing_pending_review_v2` exceed the legacy 32-char limit

## Evidence

| Step | Command / check | Result |
| --- | --- | --- |
| 1 | `generate-listing-api --category SOFA --sku meow251108Bg4d4 --strict-validation --engine v2` | `needs_review`; 2 rows inserted into `amz_listing_pending_review_v2` for `seating_capacity.value` and `sofa_type.value` (`route=human`) |
| 2 | `review-pending-attributes --category SOFA --engine v2 --approve-human --sku meow251108Bg4d4` | `human_approved=2`; both rows moved to `review_status=completed`, `reviewer=manual_cli` |
| 3 | `submit-reviewed-plans --category SOFA --engine v2` | `meow251108Bg4d4: dry_run_preview` (no `NEEDS_REVIEW` blocking) |
| 4 | `generate-listing-api --category SOFA --sku meow251108Bg4d4 --strict-validation --engine v2` | `skipped_existing`; no `needs_review`; completed review rows preserved |
| Guardrail | `generate-listing-api --engine v2 --no-dry-run` | blocked with `v2_engine_requires_dry_run` |

## Fixes Included In This Slice

- Added `ReviewAdapterV2.approve_human_pending_paths()` and CLI flag
  `--approve-human` for V2 human-route pending reviews
- `ProductListingAPIPlanBuilder` V2 path now loads approved overrides from
  `amz_listing_pending_review_v2` before building authoritative plans
- `EvidenceResolverV2` now prefers child-path review overrides over inherited
  parent LLM values (`seating_capacity.value` / `sofa_type.value` case)
- `AmazonListingPendingReviewV2Repository.upsert_pending_paths()` no longer
  resets `completed` rows back to `pending` on conflict

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
  tests/integration/repositories/test_amazon_api_submission_repository_sql_contract.py \
  tests/integration/repositories/test_amazon_listing_pending_review_v2_repository_sql_contract.py
```

Result: `176 passed`.

Ruff passed for changed files. `git diff --check` passed.

## Remaining Gate

- `ValidationPreviewV2.compare()` still needs an explicit no-unexplained-issue check
- `operation_handlers.py` split remains outstanding technical debt
- V2 code is still not in the production image; smoke used workspace-mounted source
- LIVE `--engine v2 --no-dry-run` remains blocked
