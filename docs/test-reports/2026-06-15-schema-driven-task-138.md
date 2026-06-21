# TASK-138 Schema Deep-required Coverage Gate Report

> Date: 2026-06-15  
> Agent: Cursor  
> Epic: `EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES`  
> Scope: TASK-138 / P1 "catch" phase

## 1. Goal

TASK-138 implements the first phase of the schema-driven attribute resolution
Epic: make the local required-attribute coverage gate see more than the cached
top-level `required_properties`.

The local gate now uses:

1. Product Type Definitions top-level required properties.
2. Schema-discovered required attributes from nested objects, `allOf`, and
   conditional `then` / `else` schema branches.
3. Amazon feedback learned from persisted `VALIDATION_PREVIEW` / PUT issues with
   code `90220`.

## 2. Code Changes

- `AmazonSchemaService`
  - Added `get_expanded_required_properties(product_type)`.
  - Added `get_learned_required_properties(product_type)`.
  - Added `get_coverage_required_properties(product_type)`.
  - Reused schema property merging for valid-value and description inspection.
- `AmazonAPISubmissionRepository`
  - Added `get_learned_required_attributes(product_type)` against existing
    `amazon_api_submissions.response_body->issues`.
  - No new table or migration is required for this phase.
- `AmazonListingAttributeCoverageGate`
  - Uses `get_coverage_required_properties()` when available.
  - Falls back to `get_required_properties()` for test doubles or old schema
    services.

## 3. Validation

Target tests:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_amazon_schema_service.py \
  tests/unit/services/test_amazon_listing_attribute_coverage_gate.py \
  tests/integration/repositories/test_amazon_api_submission_repository_sql_contract.py
```

Result: `23 passed`

Listing service regressions:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_product_listing_service.py \
  tests/unit/services/test_amazon_listing_submitter.py
```

Result: `37 passed`

Full regression:

```bash
./.venv/bin/pytest -q
```

Result: all tests passed.

## 4. Residual Risk

- Static schema traversal remains conservative. If Amazon marks requiredness
  through expressions not represented as direct `required` arrays, strict
  `VALIDATION_PREVIEW` remains the authority and feeds the learned-required set.
- TASK-139 is still needed to remove inapplicable attributes generically through
  schema allowlist rendering.
- TASK-140 is still needed before LLM-backed extraction can improve coverage.
