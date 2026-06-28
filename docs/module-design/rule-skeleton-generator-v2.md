# Rule Skeleton Generator V2

Schema-driven YAML rule skeleton generation for `EPIC-AMZ-LISTING-RULE-AUTHORING-V2` S1.

## Responsibility

- Reuse `RequirementTreeBuilderV2` to walk Amazon Product Type schema shapes
- Emit `api_attribute_rules/*.yaml` with:
  - Root recommendations: `dimension_strategy`, empty `coverage_ignore_required`
  - Top-level `attributes` expanded through `children` for `object`, `measure`, `array_object`
  - Structural parents without `sources`
  - Leaf path placeholders (`TODO: review source mapping for <path_key>`)

## CLI

```bash
python3 main.py --task generate-rule-skeleton-v2 --product-type CHAIR
```

Does not overwrite an existing file unless `overwrite=True` is passed programmatically.

## Boundaries

- Does not call Amazon APIs
- Does not map Giga fields (S2)
- Does not apply cross-category reuse (S3)
- Preset `amazon_universal_required_v1` still supplies universal required attributes
