# BED_FRAME Rule Authoring Pipeline — 2026-06-27

- Epic: `EPIC-AMZ-LISTING-RULE-AUTHORING-V2`
- Product type: `BED_FRAME` (`dry_run`)
- Pool: 4 pending SKUs

## Pipeline

1. Generated schema skeleton (`23` attrs / `36` leaf placeholders) via `RuleSkeletonGeneratorV2`
2. Reused TABLE patterns (`is_fragile`) + universal preset merge
3. Patched `bed_frame.yaml` v2: `item_length_width_height`, package dims, fulfillment/list_price, category defaults
4. Fixed `EvidenceResolverV2` enum transform for boolean `False` (`is_assembly_required`)

## Results

### Offline V2 coverage

| Before | After |
| --- | --- |
| 4 / 4 `missing_only` (~9 missing each) | **4 / 4 zero missing** (`clean`) |

### Rule YAML health

| Metric | Value |
| --- | --- |
| Leaf count | 48 |
| Placeholder rate | 2.1% (1 leaf) |
| `dimension_strategy` | `item_length_width_height` |

### Amazon `VALIDATION_PREVIEW`

| Status | Count |
| --- | --- |
| `validation_preview_passed` | **3 / 4** |
| `validation_preview_issues` | 1 |

| SKU | Preview | Notes |
| --- | --- | --- |
| `meow25110896fzS` | ✅ passed | |
| `meow251108FetOX` | ❌ issues | `100339` HTML in `product_description` (content pipeline, not rule gap) |
| `meow251108VJprf` | ✅ passed | |
| `meow260518aoxYQ` | ✅ passed | |

**Fix applied before preview:** removed `merchant_suggested_asin` attribute block from YAML (keep only `coverage_ignore_required`, same as TABLE). Skeleton enricher had been injecting `{marketplace_id}` shell without `value`, causing `99022` on all 4 SKUs.

Run: `python3 scripts/s7_rule_authoring_acceptance.py --preview BED_FRAME`

## Key YAML additions

- `dimension_strategy: item_length_width_height`
- `coverage_ignore_required`: merchant preview-only fields
- `item_length_width_height` + `item_package_dimensions` + `item_package_weight` from Giga dimensions
- Safe defaults: `finish_type`, `included_components`, `item_shape`, `number_of_items`, `batteries_required`
- Offer-backed: `list_price`, `condition_type`, `fulfillment_availability`

## Code changes

- `evidence_resolver_v2.py`: preserve `False` in enum `_valid_value` (was treated as empty via `value or ""`)
- `listing_payload_engine_v2.py`: candidate attrs for `item_length_width_height`
- `rule_field_mapper_v2.py`: bootstrap paths for `item_length_width_height` / package dims
- `rule_skeleton_generator_v2.py`: recommend `item_length_width_height` strategy

## S7 gate (BED_FRAME)

- Skeleton smoke: ✅
- Offline zero missing: ✅ **4 / 4**
