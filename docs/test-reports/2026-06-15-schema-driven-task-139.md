# TASK-139 Renderer Schema Allowlist Report

> Date: 2026-06-15  
> Agent: Cursor  
> Epic: `EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES`  
> Scope: TASK-139 / P2 "no invalid attributes" phase

## 1. Goal

TASK-139 implements the generic safety boundary for inapplicable attributes:
payload construction should not submit keys that are absent from the current
Amazon product type schema.

This directly addresses the HOME_MIRROR warning class found after TASK-137:

- `item_depth`
- `item_type_name`
- `item_width`
- `item_height`
- `target_audience_base`

## 2. Code Changes

- `AmazonSchemaService`
  - Added `get_property_names(product_type)` to expose the product type schema
    property allowlist, including root, `allOf`, and conditional properties.
- `AttributePayloadRenderer`
  - Added optional `allowed_attributes` filtering.
  - Added generic `filter_allowed_attributes()`.
  - Added shape support for `measure` and `object` / `nested_object`.
- `AmazonListingPayloadBuilder`
  - Added a final schema allowlist pass after hardcoded attributes, YAML rules,
    product-type normalization, configured removal, and required defaults.
  - The pass is fail-open if schema service or schema property names are
    unavailable, preserving offline dry-run behavior.

## 3. Validation

Target tests:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_amazon_schema_service.py \
  tests/unit/services/test_attribute_resolver.py \
  tests/unit/services/test_amazon_listing_payload_builder.py
```

Result: `30 passed`

Listing quality regressions:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_product_listing_service.py \
  tests/unit/services/test_amazon_listing_submitter.py \
  tests/unit/services/test_amazon_listing_quality_gate.py
```

Result: `44 passed`

Full regression:

```bash
./.venv/bin/pytest -q
```

Result: all tests passed.

Whitespace check:

```bash
git diff --check
```

Result: passed.

## 4. Residual Risk

- This is still a generic allowlist filter, not full schema shape validation.
  TASK-140 and TASK-141 remain responsible for moving more attribute construction
  into resolver/renderer/config and reducing builder hardcode.
- Strict `VALIDATION_PREVIEW` remains required before LIVE submission because
  Amazon may still enforce conditional rules beyond static schema inspection.
