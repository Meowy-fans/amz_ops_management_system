# Category Onboarding V2 (S8)

> Module: `src/services/category_onboarding_v2.py`
> Slice: S8 orchestration

## CLI

```bash
python3 main.py --task onboard-category-v2 --category BED_FRAME \
  --reference TABLE --sample-skus 4 --run-s7-offline
```

## Pipeline

1. Validate cached schema + category SKU pool
2. `generate-rule-skeleton-v2` (overwrite)
3. `reuse-rule-patterns-v2` when `--reference` set
4. `map-rule-fields-v2` on pool SKUs (optional `--sample-skus` limit)
5. `review-pending-rules`
6. Optional S7 offline/preview acceptance (`--run-s7-offline`, `--run-s7-preview`)

## Outputs

| Artifact | Path |
| --- | --- |
| YAML rules | `config/.../api_attribute_rules/{category}.yaml` |
| State manifest | `config/.../category_rule_state/{category}.json` |
| Acceptance report | `docs/test-reports/{date}-{category}-onboard-acceptance.json` |

## Operator hooks (manual)

After onboard, operators may still patch GTIN exemption / MSA omit /
`dimension_strategy` before `approve-rule` and `promote-category-rules-v2`.
