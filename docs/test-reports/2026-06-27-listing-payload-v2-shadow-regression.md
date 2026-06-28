# Listing Payload Engine V2 Shadow Regression - 2026-06-27

## Scope

Read-only / dry-run validation for `EPIC-AMZ-LISTING-REQUIREMENT-PAYLOAD-V2`.
All commands used the current workspace source mounted into the production
Docker runtime and kept V1 as the authoritative listing path.

No `PUT` submission was executed.

## Summary

Default regression evaluator result:

```text
status=go total=5 go=5 no_go=0 limit_per_category=20
  CABINET: decision=go mode=live_regression rows=1 blocking=- reasons=-
  HOME_MIRROR: decision=go mode=live_regression rows=1 blocking=- reasons=-
  OTTOMAN: decision=go mode=live_regression rows=2 blocking=- reasons=-
  CHAIR: decision=go mode=exploratory rows=1 blocking=MISSING_REQUIRED_ATTRIBUTE_RULE,NEEDS_REVIEW_REQUIRED_ATTRIBUTE reasons=-
  SOFA: decision=go mode=exploratory rows=1 blocking=MISSING_REQUIRED_ATTRIBUTE_RULE,NEEDS_REVIEW_REQUIRED_ATTRIBUTE reasons=-
```

The regression evaluator now evaluates the latest shadow row per SKU, so older
failed rows do not pollute category go/no-go.

## Evidence

| Product type | SKU / scope | Evidence | Result |
| --- | --- | --- | --- |
| CABINET | `meow251115FC0ie` | Latest shadow submission `114150`; V1 strict path `skipped_existing` | V2 attrs=31, missing=0, pending=0, blocking=0; regression `go` |
| HOME_MIRROR | `meow251108CqW5i` | Latest shadow submission `115998`; V1 strict path `skipped_existing` | V2 attrs=26, missing=0, pending=0, blocking=0; regression `go` |
| OTTOMAN | `meow2511088jSUW`, `meow260518LZZCw` | Full-family shadow run; V1 parent `PARENT-FE6D7B7BD7A8` validation preview passed, children skipped existing; latest V2 rows `116002` and `116003` | Both SKUs missing=0, pending=0, blocking=0; regression `go` |
| CHAIR | `meow2511081Gqqd` | Latest shadow submission `116007`; V1 blocked at old flat coverage before submit | V2 attrs=22, missing=7, pending=2, blocking explainable by missing rules / pending review; exploratory regression `go` |
| SOFA | `meow251108Bg4d4` | Latest stored shadow submission `116008` was built before SOFA seat rule fix; rerun later hit V1 variation-resolution block before shadow hook | Stored row remains exploratory `go`; direct V2 read-only plan after rule update has missing=0 and pending review only for `seating_capacity.value` / `sofa_type.value` |

## Fixes Included In This Slice

- Shadow diff SKU filter is case-insensitive.
- Shadow diff CLI prints missing, pending, and low-confidence path details.
- `EvidenceResolverV2` falls back to deterministic candidate attributes and can
  inherit scalar-list / list-of-dict child values.
- `PayloadComposerV2` renders generic `array_object` scalar and scalar-list
  shapes.
- `ListingPayloadEngineV2` candidate attributes include deterministic physical,
  material, offer, fulfillment, model, and part fields already available to V1.
- `CoverageGateV2` supports rule-driven `coverage_ignore_required`.
- CABINET, HOME_MIRROR, OTTOMAN, and SOFA rules now ignore V1-non-submitted
  `merchant_shipping_group` / `merchant_suggested_asin` where needed.
- SOFA `seat` is now configured as a structured object with `depth`, `height`,
  `interior_width`, `fill_material`, and `material_type` child rules.

## Verification

```bash
.venv/bin/pytest tests/unit/cli/test_listing_handlers.py \
  tests/unit/cli/test_task_dispatcher.py \
  tests/unit/cli/test_operation_handlers.py \
  tests/integration/cli/test_main_non_interactive_entrypoint.py \
  tests/unit/services/test_product_listing_api_plan_builder.py \
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

Result: `127 passed`.

```bash
.venv/bin/ruff check <changed V2/CLI/repository/test files>
git diff --check
```

Result: ruff passed; no whitespace errors.

## Remaining Gate Before V2 Replacement

- `LISTING_PAYLOAD_ENGINE=v2` remains blocked at the listing entrypoint.
- Live categories have shadow regression `go`, but V2 replacement still needs a
  canary path in `ProductListingAPIPlanBuilder` that uses V2 attributes and V2
  coverage as the authoritative dry-run path before any LIVE PUT.
- CHAIR and SOFA are exploratory only; their blocking remains acceptable only
  because it is explainable as missing evidence/rules or pending review.
