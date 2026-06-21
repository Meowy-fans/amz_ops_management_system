# TASK-141 PayloadBuilder Slimming Report

> Date: 2026-06-15  
> Agent: Cursor  
> Epic: `EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES`  
> Scope: TASK-141 / P4 "slim builder" phase

## 1. Goal

TASK-141 removes the remaining product-type specific branches from
`AmazonListingPayloadBuilder` while preserving the CABINET behavior already
validated by strict dry-run.

The builder should orchestrate generic rendering and defer product-type
differences to configuration and helper modules.

## 2. Code Changes

- `config/amz_listing_data_mapping/api_attribute_rules/cabinet.yaml`
  - Added `dimension_strategy: item_depth_width_height`.
  - Added `post_processors: [cabinet_attribute_shapes]`.
- `AmazonListingPayloadBuilder`
  - Removed direct CABINET checks from dimension rendering.
  - Removed direct import/call of `normalize_cabinet_attributes`.
  - Reads `dimension_strategy` from product-type YAML.
  - Runs configured post processors through a generic dispatcher.
- Added `attribute_post_processors.py`
  - Provides `apply_attribute_post_processors()`.
  - Contains the concrete registry for configured post processors.

## 3. Validation

TASK-141 target tests:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_amazon_listing_payload_builder.py \
  tests/unit/services/test_attribute_post_processors.py \
  tests/unit/services/test_attribute_resolver.py
```

Result: `23 passed`

Listing regressions:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_product_listing_service.py \
  tests/unit/services/test_amazon_listing_submitter.py \
  tests/unit/services/test_amazon_listing_quality_gate.py \
  tests/unit/services/test_amazon_variation_resolver.py
```

Result: `51 passed`

Schema pipeline regressions:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_amazon_schema_service.py \
  tests/unit/services/test_llm_attribute_extractor.py \
  tests/unit/services/test_amazon_listing_attribute_coverage_gate.py
```

Result: `21 passed`

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

- This task removes product-type branches from `AmazonListingPayloadBuilder`, but
  product-type-specific behavior still exists in dedicated helper modules and is
  selected by YAML. That is intentional for this phase.
- Full removal of legacy Excel modules remains governed by the existing Excel
  retirement plan.
