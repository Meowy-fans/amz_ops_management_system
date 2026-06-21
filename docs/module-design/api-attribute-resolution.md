# API-native Attribute Resolution Design

> Status: Draft
> Owner: amz-listing-management-system
> Decision: New listing creation is API-native only. Excel listing generation is deprecated as an operations path.

## 1. Business Goal

The system must support multi-category Amazon listing creation through SP-API without adding category-specific Python hardcode for every product type.

The business objective is not only to satisfy the minimum Amazon required fields. The listing payload should provide rich, accurate, structured product attributes so Amazon search, browse classification, COSMO, Rufus, and future AI shopping experiences can understand the product correctly.

## 2. Confirmed Facts

- `generate-listing-api` is the primary listing creation flow.
- `generate-listing` / Excel listing generation is deprecated and should not be used for operations.
- Amazon Product Type Definitions schema is the external authority for product type attributes, valid values, and required fields.
- Giga raw data is a supplier fact source, but its attributes are inconsistent across categories.
- LLM output can enrich or extract candidate attributes, but it is not an authoritative fact source without evidence and confidence.
- Amazon `VALIDATION_PREVIEW`, PUT response issues, and GET confirmation issues are authoritative feedback and must feed future mapping improvements.

## 3. Non-goals

- Do not expand CABINET support by adding many `if product_type == "CABINET"` branches in `AmazonListingPayloadBuilder`.
- Do not ask the LLM to generate final Amazon attributes JSON directly.
- Do not keep Excel template parsing as a primary source for new listing payload construction.
- Do not require all future categories to be implemented through code changes.

## 4. Core Objects

| Object | Definition |
| --- | --- |
| `AmazonProductTypeSchema` | Cached Product Type Definitions schema plus required fields, valid values, schema version/hash, and fetch time. |
| `AttributeDefinition` | One Amazon attribute for a product type, including level, shape, valid values, descriptions, and constraints. |
| `AttributeMappingRule` | Configured rule that explains how to resolve one Amazon attribute from supplier data, normalized data, LLM enrichment, derived logic, default, or manual review. |
| `AttributeResolution` | The resolved value for one SKU and attribute, with source, evidence, confidence, and validation state. |
| `AttributeEvidence` | Traceable source detail, such as raw Giga path, normalized field, LLM extraction prompt/version, family inheritance, or manual confirmation. |
| `LLMAttributeExtraction` | Evidence-bound candidate extracted from product text. It is not authoritative and is capped at medium confidence. |
| `ValidationFeedback` | Amazon validation preview, PUT, or GET issue normalized into field-level feedback. |
| `ManualAttributeReview` | Queue item for required or high-value attributes that cannot be resolved with sufficient confidence. |

## 5. Attribute Levels

| Level | Meaning | Handling |
| --- | --- | --- |
| `required` | Amazon may reject the listing without it. | Must resolve or block before LIVE submit. |
| `recommended` | Strong search/browse/AI signal. | Resolve when confidence is high; otherwise warn or review. |
| `ai_enrichment` | Helps Amazon AI understand use cases, audience, style, and scenarios. | Prefer evidence-backed LLM extraction; avoid invented facts. |
| `optional` | Low-risk additional data. | Fill when directly available. |

## 6. Main Flow

1. Sync or refresh Product Type Definitions schema for the target product type.
2. Build a normalized `StandardProduct` from Giga and local product data.
3. Load product-type attribute mapping rules from config.
4. Resolve attributes through the generic `AttributeResolver`.
5. Produce an attribute coverage report:
   - required coverage
   - recommended coverage
   - low-confidence fields
   - default-filled fields
   - fields needing manual review
6. Run local schema and value validation.
7. Run Amazon `VALIDATION_PREVIEW` in strict dry-run mode when requested.
8. Submit LIVE only when blocking gates pass.
9. Store PUT/GET feedback as `ValidationFeedback`.
10. Feed repeated issues back into mapping rule review.

## 7. Resolution State Machine

```text
unresolved
  -> resolved_high_confidence
  -> resolved_with_default
  -> resolved_low_confidence
  -> needs_manual_review
  -> validated_by_local_schema
  -> validated_by_amazon
  -> rejected_by_amazon
```

Rules:

- `required` attributes may not proceed to LIVE in `unresolved`, `resolved_low_confidence`, or `needs_manual_review`.
- `recommended` and `ai_enrichment` attributes may proceed with warnings if unresolved.
- Amazon rejection creates or updates `ValidationFeedback` and should be queryable by product type, attribute, issue code, and mapping rule.
- Default values must include evidence and confidence. Low-confidence defaults for required attributes block LIVE.

## 8. Configuration Contract

Product-type differences belong in config, not Python branches. A first version can use YAML or JSON under `config/amz_listing_data_mapping/api_attribute_rules/`.

Example:

```yaml
product_type: CABINET
version: cabinet_attribute_rules_v1
attributes:
  mounting_type:
    level: required
    shape: list_value
    sources:
      - path: normalized.attributes.Mounting Type
      - path: raw.attributes.Mounting Type
      - default: Freestanding
        confidence: high
        evidence: CABINET safe default for freestanding furniture when no wall-mount signal exists
    transform: enum

  is_assembly_required:
    level: required
    shape: list_value
    sources:
      - path: normalized.attributes.Assembly Required
      - path: raw.attributes.Assembly Required
      - default: true
        confidence: medium
        evidence: Supplier flat-pack furniture default; review if product text says no assembly
    transform: boolean_yes_no

  special_feature:
    level: recommended
    shape: list_value
    sources:
      - path: llm.enriched_attributes.special_feature
      - path: normalized.attributes.Special Feature
    transform: text
    low_confidence_policy: warn
```

TASK-140 adds native `llm` source support so rules can express constrained
extraction without relying on a fake `llm.*` path:

```yaml
room_type:
  level: recommended
  shape: list_value
  sources:
    - path: product.attributes.Room Type
    - llm:
        hint: Extract room placement from product text. Return null if absent.
        enum_locked: true
    - default: Living Room
      confidence: medium
      evidence: Common furniture placement; fallback only.
  transform: text
```

LLM extraction contract:

- The extractor returns `null` when no value is evidenced in source text.
- Evidence is required; no-evidence output is discarded.
- `enum_locked: true` restricts output to cached schema valid values.
- Sensitive fields such as brand, identifiers, GTIN, compliance declarations,
  certifications, and supplier-declared regulatory fields are rejected before
  any LLM call.
- LLM confidence is capped at `medium`.
- Required attributes resolved by LLM become `needs_manual_review` and remain
  blocking; they do not silently proceed to LIVE.

## 9. Required Coverage Gate

`AmazonListingAttributeCoverageGate` is the local fail-closed boundary for
Amazon schema required fields.

Inputs:

- A rendered listing plan with `product_type`, `attributes`, and optional
  `attribute_resolutions`.
- `AmazonSchemaService.get_coverage_required_properties(product_type)`, which
  merges:
  - cached Product Type Definitions top-level `required_properties`
  - schema-discovered nested / `allOf` / conditional required attributes
  - Amazon `VALIDATION_PREVIEW` / PUT feedback learned from historical
    `MISSING_REQUIRED_ATTRIBUTE` (`90220`) issues

Decision rules:

- Required attributes present in payload are covered.
- Required attributes missing from payload return `blocked_attribute_coverage`
  before `AmazonListingSubmitter` receives the plan.
- Required attributes resolved with `confidence: low` or
  `resolved_low_confidence` are blocking even if a payload value exists.
- Required defaults with `confidence: medium` or `high` are allowed only when
  they include evidence in the YAML rule.
- Schema lookup failures are fail-open with a warning so offline dry-run remains
  usable; `AmazonListingQualityGate` and strict dry-run remain later defenses.

Pre-submit result shape:

```json
{
  "status": "blocked_attribute_coverage",
  "blocking_codes": ["MISSING_REQUIRED_ATTRIBUTE_RULE"],
  "missing_required": ["fabric_type"],
  "attribute_coverage_findings": []
}
```

This turns weakly relevant Amazon-required attributes, such as
`HOME_MIRROR.fabric_type`, into explicit rule decisions instead of category
hardcode in `AmazonListingPayloadBuilder`.

## 10. Module Boundaries

| Module | Responsibility |
| --- | --- |
| `AmazonSchemaService` | Fetch/cache schema and expose field definitions, required fields, valid values, and schema hash. |
| `AttributeRuleRepository` or config loader | Load product-type mapping rules. |
| `AttributeResolver` | Resolve field values with evidence and confidence. |
| `AttributePayloadRenderer` | Convert resolved fields into Listings Items API attribute JSON shapes and drop keys outside the product type schema allowlist. |
| `AmazonListingAttributeCoverageGate` | Block missing or low-confidence schema required attributes before submitter. |
| `AmazonListingQualityGate` | Block unsafe, missing, stale, or low-confidence required attributes. |
| `AmazonListingSubmitter` | Run validation preview/PUT/confirmation and persist Amazon feedback. |

`AmazonListingPayloadBuilder` should become a thin orchestration adapter or be replaced by `AttributePayloadRenderer`. It should not own category-specific business rules.

TASK-139 adds an interim safety boundary while `AmazonListingPayloadBuilder` is
being slimmed down: after all hardcoded, config-driven, normalized, and required
default attributes are assembled, the builder asks `AmazonSchemaService` for the
current product type's schema property names and drops any attribute outside that
allowlist. The behavior is fail-open when schema is unavailable so offline
dry-run remains usable, and strict validation preview remains the authoritative
external check.

TASK-141 removes the remaining product-type branches from
`AmazonListingPayloadBuilder` by moving them behind product-type configuration:

- `dimension_strategy` controls whether dimensions render as separate
  `item_width` / `item_depth` / `item_height` measures or as a combined
  `item_depth_width_height` object.
- `post_processors` names schema-shape normalizers that run after resolver output
  is merged. The builder only executes configured processor names; the concrete
  processor registry lives outside the builder.

Example:

```yaml
dimension_strategy: item_depth_width_height
additional_dimension_measures:
  - item_width
post_processors:
  - cabinet_attribute_shapes
coverage_ignore_when_parent:
  - item_width
```

The coverage gate intentionally keeps static schema required extraction
conservative: only cached top-level/direct `required` plus Amazon preview-learned
`MISSING_REQUIRED_ATTRIBUTE` feedback are treated as blocking required
attributes. Deep nested object required fields and conditional schema branches
are not promoted automatically, because Amazon Product Type schemas contain many
branch-specific compliance and offer fields that are not applicable to every
listing. When a learned required attribute is child-only in a variation family,
product-type config can exclude it from parent plans with
`coverage_ignore_when_parent`.

## 11. Excel Deprecation

Deprecated operations:

- `generate-listing` as an Excel generation command.
- Excel template parsing as a required setup step for a new product type.
- Amazon upload workbook generation as a production listing creation path.

Allowed temporarily:

- Reading historical template data for migration comparison.
- Legacy unit tests that protect old helpers until the modules are removed.
- One-off forensic analysis of old submissions.

Exit criteria for full removal:

- `generate-listing-api` has strict dry-run with validation preview.
- Attribute resolver supports CABINET and OTTOMAN without category-specific Python hardcode.
- Web/CLI no longer exposes Excel listing generation.
- Remaining Excel modules are either moved under legacy namespace or removed with tests.

## 12. Acceptance Criteria for Phase 1

- `generate-listing-api` is the only documented and menu-visible new listing creation entry point.
- `generate-listing` prints a deprecation notice and does not generate Excel workbooks.
- CABINET and OTTOMAN attribute construction runs through the generic resolver path.
- CABINET 18-SKU test set can produce an attribute coverage report.
- Strict dry-run can call Amazon `VALIDATION_PREVIEW` without PUT.
- No new product-type branch is added to `AmazonListingPayloadBuilder` except temporary compatibility shims approved in this document.
- Tests cover resolver source priority, enum alignment, default evidence, low-confidence blocking, and renderer output shape.
