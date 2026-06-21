# OTTOMAN API-native Resolver Regression

- **Date**: 2026-06-15
- **Task**: TASK-130
- **Scope**: `meow2511088jSUW`, `meow260518LZZCw`
- **Baseline**: `docs/acceptance/ottoman-e2e-2026-05-18.md`
- **Execution directory**: production container temporary code path `/tmp/codex-amz-task129`
- **PUT behavior**: no PUT; strict dry-run only

## Command

```bash
python main.py \
  --task generate-listing-api \
  --category OTTOMAN \
  --sku meow2511088jSUW \
  --sku meow260518LZZCw \
  --strict-validation
```

## Changes Validated

1. Added `OTTOMAN` variation resolver config in `config/listing_gates/variation_theme_strategy.yaml`.
2. Normalized generic variation theme `Color` to Amazon value `COLOR`.
3. Added OTTOMAN `fabric_type` attribute rule sourced from supplier fabric/material fields.
4. Added configurable `remove_attributes` for OTTOMAN to suppress Amazon-inapplicable attributes found by `VALIDATION_PREVIEW`.

## Result

| SKU | Status | Request ID | Issues |
| --- | --- | --- | ---: |
| PARENT-2B500764CF03 | validation_preview_passed | e9eefd4b-4754-408e-a140-07b81b5a9a68 | 0 |
| meow260518LZZCw | skipped_existing | - | - |
| meow2511088jSUW | skipped_existing | - | - |

## Regression Assertions

| Check | Result |
| --- | --- |
| API-native plan builder generated 1 parent + 2 child plans | PASS |
| OTTOMAN variation family selected `Color` / payload rendered `COLOR` | PASS |
| Required `fabric_type` rendered as `Linen` | PASS |
| Parent quantity is `0` | PASS |
| Amazon `VALIDATION_PREVIEW` for generated parent returned 0 issues | PASS |
| Existing children were protected by real-time existing-listing check | PASS |

## Conclusion

TASK-130 is accepted. The OTTOMAN regression path remains green through the API-native resolver and strict dry-run path. No live listing PUT was executed.
