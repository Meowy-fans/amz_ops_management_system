# TASK-140 LLM Constrained Attribute Extraction Report

> Date: 2026-06-15  
> Agent: Cursor  
> Epic: `EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES`  
> Scope: TASK-140 / P3 "fill with low-fabrication risk" phase

## 1. Goal

TASK-140 wires a constrained LLM extraction layer into `AttributeResolver` while
keeping the default path safe: no automatic external LLM call is made unless an
extractor/client is explicitly injected.

The goal is to recover attributes that are present in product text but missing
from structured supplier fields, without letting the LLM invent final Amazon
attribute values.

## 2. Code Changes

- Added `LLMAttributeExtractor`
  - Returns `LLMAttributeExtraction(value, evidence, confidence, warnings)`.
  - Rejects sensitive fields before LLM call.
  - Requires non-empty evidence.
  - Supports `enum_locked` validation against cached schema valid values.
  - Caps confidence at `medium`.
  - Returns null results when no client is injected.
- Updated `AttributeResolver`
  - Added optional `llm_extractor` dependency injection.
  - Added support for YAML sources shaped as:
    ```yaml
    - llm:
        hint: Extract from product text; return null if absent.
        enum_locked: true
    ```
  - Keeps source priority intact: structured path -> LLM -> default.
  - Marks required attributes resolved by LLM as `needs_manual_review` and
    blocking, so they cannot silently proceed to LIVE.

## 3. Validation

TASK-140 target tests:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_attribute_resolver.py \
  tests/unit/services/test_llm_attribute_extractor.py
```

Result: `10 passed`

Schema attribute pipeline tests:

```bash
./.venv/bin/pytest -q \
  tests/unit/services/test_amazon_schema_service.py \
  tests/unit/services/test_attribute_resolver.py \
  tests/unit/services/test_llm_attribute_extractor.py \
  tests/unit/services/test_amazon_listing_payload_builder.py \
  tests/unit/services/test_amazon_listing_attribute_coverage_gate.py
```

Result: `41 passed`

Listing regressions:

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

- No production prompt or external LLM client adapter is enabled in this task.
  That is intentional; extraction remains injectable and testable.
- Required attributes extracted by LLM remain blocking until reviewed or replaced
  by a higher-authority source/default.
- TASK-141 is still needed to migrate remaining builder-owned category behavior
  into resolver/renderer/config.
