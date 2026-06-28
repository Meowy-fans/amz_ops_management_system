# Listing Payload Engine V2 CABINET Shadow Evidence

Date: 2026-06-27
Agent: Codex

## Scope

- Product type: `CABINET`
- SKU: `meow251115FC0ie`
- Entry point: `generate-listing-api --engine shadow --strict-validation`
- Runtime: temporary Docker container using current workspace source, production env files, and Docker `proxy` network.
- Safety: dry-run only. V1 behavior remained authoritative; V2 wrote shadow audit rows only.

## Fixes Validated

1. Shadow diff SKU filtering is now case-insensitive.
2. `report-listing-shadow-diff-v2` prints missing, pending, and low-confidence path details.
3. `PayloadComposerV2` renders `array_object` scalar and scalar-list parent values generically.
4. `EvidenceResolverV2` inherits scalar-list and list-of-dict child values from parent resolutions.
5. `EvidenceResolverV2` falls back to V2 candidate attributes when explicit rules do not resolve a path.
6. `ListingPayloadEngineV2` candidate attributes now include deterministic physical fields already supported by V1: color, material, dimensions, weight, part number, model number, offer, and fulfillment.
7. `CoverageGateV2` supports rule-driven `coverage_ignore_required` for known non-submitted schema fields. CABINET now ignores `merchant_shipping_group` and `merchant_suggested_asin`, matching current V1 non-submission behavior.

## Evidence Timeline

| Submission | V2 attrs | Missing | Low confidence | Blocking |
| --- | ---: | ---: | ---: | --- |
| `114140` | 20 | 13 | 0 | yes |
| `114142` | 22 | 11 | 0 | yes |
| `114144` | 27 | 6 | 2 | yes |
| `114146` | 27 | 6 | 0 | yes |
| `114148` | 31 | 2 | 0 | yes |
| `114150` | 31 | 0 | 0 | no |

Final latest diff:

```text
rows=1 product_type=CABINET sku=MEOW251115FC0IE limit=1
summary: shadow_built=1 shadow_failed=0 v2_blocking=0 with_pending_review=0 with_missing_required=0
  meow251115FC0ie: shadow=shadow_built v1=plan_generated v1_attrs=43 v2_attrs=31 missing=0 pending=0 blocking_codes=-
```

Final latest regression:

```text
status=go total=1 go=1 no_go=0 limit_per_category=1
  CABINET: decision=go mode=live_regression rows=1 blocking=- reasons=-
```

V1 strict path result for this SKU remained `skipped_existing`; no PUT was performed.

## Verification

```text
.venv/bin/pytest tests/unit/cli/test_listing_handlers.py tests/unit/cli/test_task_dispatcher.py tests/unit/cli/test_operation_handlers.py tests/integration/cli/test_main_non_interactive_entrypoint.py tests/unit/services/test_product_listing_api_plan_builder.py tests/unit/services/test_listing_payload_shadow_adapter_v2.py tests/unit/services/test_listing_payload_shadow_diff_v2.py tests/unit/services/test_listing_payload_v2_regression.py tests/unit/services/test_listing_payload_engine_v2.py tests/unit/services/test_evidence_resolver_v2.py tests/unit/services/test_confidence_scorer_v2.py tests/unit/services/test_review_adapter_v2.py tests/unit/services/test_coverage_gate_v2.py tests/unit/services/test_payload_composer_v2.py tests/integration/repositories/test_amazon_api_submission_repository_sql_contract.py
124 passed

.venv/bin/ruff check <changed V2/CLI/repository/test files>
All checks passed
```

## Remaining Work

- Collect equivalent shadow/strict-preview evidence for `HOME_MIRROR`, `OTTOMAN`, `CHAIR`, and `SOFA`.
- Update regression evaluator to prefer latest shadow rows per SKU before using multi-row category history as a canary gate.
- Do not enable `LISTING_PAYLOAD_ENGINE=v2` until the live regression category set has parity evidence.
