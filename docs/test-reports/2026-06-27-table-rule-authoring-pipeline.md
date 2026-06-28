# TABLE Rule Authoring Pipeline — 2026-06-27

- Epic: `EPIC-AMZ-LISTING-RULE-AUTHORING-V2`
- Product type: `TABLE` (`dry_run`)
- Pool: 4 pending SKUs

## Pipeline

1. Baseline backup: `table.yaml.baseline`
2. Authored `table.yaml` v2 (nested `array_object` children, `dimension_strategy`, coverage ignore)
3. Enhanced `OptionalRuleChildrenEnricherV2` to bootstrap empty `array_object` parents (frame)
4. Added `top.material` for Amazon 90220 preview path

## Results

### Offline V2 coverage

| Before | After |
| --- | --- |
| 4 / 4 `missing_and_review` (5–6 missing + 3–4 pending) | **4 / 4 zero missing** (`findings_only`) |

### Amazon `VALIDATION_PREVIEW`

| Status | Count |
| --- | --- |
| `validation_preview_passed` | **3 / 4** |
| `validation_preview_issues` | 1 |

| SKU | Preview | Notes |
| --- | --- | --- |
| `meow2511086pcXe` | ✅ passed | |
| `meow251108FAsJo` | ✅ passed | |
| `meow251108PlHb2` | ✅ passed | |
| `meow251108uwb5L` | ❌ issues | `90244` `country_of_origin=VIET NAM` (supplier data, not rule gap) |

## Key YAML additions

- `dimension_strategy: item_depth_width_height`
- `coverage_ignore_required`: merchant preview-only fields
- Structured `frame.material`, `top.color` + `top.material`, `item_depth_width_height`, `item_weight`
- Safe defaults on `is_fragile`, `included_components`, `item_shape`, `number_of_items`

## Code changes

- `optional_rule_children_enricher_v2.py`: bootstrap missing `array_object` parent shells
- `rule_migration_v2.py`: prefer skeleton children over flat TODO legacy blocks (dry_run)

## S7 gate (TABLE)

- ≥1 SKU not `missing_only`: ✅ (was already true; now **zero missing**)
- ≥1 preview passed: ✅ **3 / 4**

## Follow-up

1. Map `VIET NAM` / `MALAYSIA` → ISO country codes in candidate attributes or Giga normalizer
2. Optional: reduce `findings_only` low-confidence on `frame` if blocking strict paths later
