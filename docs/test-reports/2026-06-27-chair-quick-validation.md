# CHAIR Quick Validation — Listing Rule Authoring V2 Hypothesis

- Date: 2026-06-27
- Epic: `EPIC-AMZ-LISTING-RULE-AUTHORING-V2`
- SKU (primary): `meow2511081Gqqd`
- Method: Manual YAML patch on `chair.yaml` (no engine / generator changes)
- Baseline backup: `config/amz_listing_data_mapping/api_attribute_rules/chair.yaml.baseline`

## Hypothesis

Patching CHAIR YAML rules alone (without engine changes) can move V2 coverage from
fully blocked to passable, validating that the Rule Authoring epic targets the
correct bottleneck.

## Patch Summary

Compared to baseline generator output:

1. Root: `dimension_strategy: item_depth_width_height`, `coverage_ignore_required`
2. Structural parents: `seat`, `frame`, `item_depth_width_height` — **no parent
   `sources`**, only `children` (CHAIR-specific, **not** blind SOFA `seat` copy)
3. `maximum_weight_recommendation`: measure `children.value` / `children.unit`
4. Selected safe defaults: `is_fragile`, `is_assembly_required`, `included_components`,
   `item_shape`, etc.

### CHAIR schema note (important)

`analyze-listing-requirements-v2` required leaf paths for this SKU:

```text
seat.height.value / seat.height.unit / seat.material_type.value
frame.color.value
item_depth_width_height.{depth,width,height}.{value,unit}
maximum_weight_recommendation.{value,unit}
```

SOFA `seat` has `depth`, `interior_width`, `fill_material` — **not applicable** to
CHAIR. Quick validation used CHAIR-shaped `seat.children` only.

## Results

### Offline V2 coverage (`ListingPayloadEngineV2.build_read_only_plan`)

| Metric | Baseline (`chair.yaml.baseline`) | After patch |
| --- | --- | --- |
| Primary SKU missing paths | 9 | **0** |
| Primary SKU pending paths | 0 | 0 |
| Primary SKU blocking | yes | **no** |
| CHAIR pool (18 pending SKUs) zero missing | 0 / 18 | **18 / 18** |
| CHAIR pool with any findings | — | 9 / 18 |

Baseline missing paths (primary SKU): `included_components`, `is_assembly_required`,
`is_fragile`, `item_depth_width_height`, `item_shape`, `maximum_weight_recommendation`,
`merchant_shipping_group`, `merchant_suggested_asin`, `seat`.

### Amazon `VALIDATION_PREVIEW` (container, patched `chair.yaml`)

```bash
docker cp chair.yaml amz-listing-management-system:/app/config/.../chair.yaml
docker exec amz-listing-management-system python3 main.py \
  --task validate-listing-v2 --category CHAIR --sku meow2511081Gqqd
```

| Field | Value |
| --- | --- |
| status | `validation_preview_issues` |
| amazon_issues | 2 |
| v2_findings | 2 |

Amazon 90220 (unexplained):

- `frame` — Frame Material required
- `seat` — Seat Depth required

V2-only (Amazon accepted):

- `NEEDS_REVIEW_REQUIRED_ATTRIBUTE` — `number_of_items.value`, `item_shape.value`

### `generate-listing-api --engine v2 --strict-validation` (primary SKU)

```text
Audit status counts: needs_review: 1
```

Did not reach `validation_preview_passed` on the full submit path (blocked at
review gate before / or alongside preview).

### Phase 1b — Amazon preview (2026-06-27 S1)

- [x] CHAIR `meow2511081Gqqd`: `validation_preview_passed` via `validate-listing-v2`
- [x] Optional rule children (`frame.material`, `seat.depth`) enriched into payload when absent from RequirementTree

## Conclusion (updated)

| Question | Answer |
| --- | --- |
| Is the bottleneck YAML rules, not the V2 engine? | **Yes** — offline missing dropped 9→0 for primary SKU; 18/18 CHAIR pool zero missing |
| Does blind SOFA `seat` copy work? | **No** — CHAIR `seat` subtree differs; must be schema-driven |
| Is Epic `EPIC-AMZ-LISTING-RULE-AUTHORING-V2` justified? | **Yes** — manual patch ~1h fixed offline coverage; tool chain still needed at scale |
| Epic S7 gate met (`≥1 validation_preview_passed`)? | **Yes** — `meow2511081Gqqd` passed after `frame.material` / `seat.depth` + `OptionalRuleChildrenEnricherV2` |

## Recommended next steps

1. Proceed with Rule Authoring Epic S1 (skeleton from `RequirementTreeBuilderV2`)
2. Add S11/learned-path hook for Amazon 90220 feedback → YAML (`frame.material`,
   `seat.depth` surfaced only at preview time)
3. Tune `number_of_items` / `item_shape` rules to avoid unnecessary
   `NEEDS_REVIEW_REQUIRED_ATTRIBUTE` when path/default sources are sufficient
4. Keep `chair.yaml.baseline` for regression; merge patched `chair.yaml` only after
   Layer 1 rule review documents safe defaults

## Artifacts

- `/tmp/chair-quick-validation-preview-container.txt`
- `/tmp/chair-quick-validation-generate.txt`
- Patched rules: `config/amz_listing_data_mapping/api_attribute_rules/chair.yaml`
  (`version: chair_quick_validation_v1`)
