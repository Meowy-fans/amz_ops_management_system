# API-native Multi-category Listing System Design

> Status: Draft
> Date: 2026-06-13
> Scope: Amazon new listing creation, multi-category attribute enrichment, content generation review, validation, and submission.

## 1. Business Definition

The system creates high-quality Amazon listings from supplier products through SP-API. It must support multiple product types without category-specific Python hardcode and must provide rich, accurate, structured attributes for Amazon search, browse classification, COSMO, Rufus, and future AI shopping experiences.

## 2. Roles

| Role | Responsibility |
| --- | --- |
| Operator | Select categories/SKUs, inspect dry-run reports, approve manual review items. |
| Content Generator LLM | Generate listing content and candidate enriched attributes from source facts. |
| Content Reviewer LLM | Review generated content for factual accuracy, Amazon policy, and listing quality. |
| Attribute Resolver | Convert source facts and reviewed enrichment into Amazon attributes with evidence. |
| Amazon SP-API | Authoritative validation and submission endpoint. |

## 3. Core Goals

1. New listing creation uses `generate-listing-api` only.
2. Excel listing generation is deprecated and not exposed as an operations path.
3. Multi-category support is config/schema driven, not Python branch driven.
4. LLM-generated content must be reviewed before it can feed listing submission.
5. Every generated content field and resolved API attribute must be auditable by source, confidence, and validation result.
6. Amazon `VALIDATION_PREVIEW`, PUT issues, and GET confirmation issues must feed a continuous mapping improvement loop.

## 4. Non-goals

- Build a generic marketplace listing platform for non-Amazon channels.
- Let LLM output final Amazon SP-API attributes without deterministic rendering.
- Bypass Amazon Product Type Definitions schema.
- Keep Excel templates as the source of truth for new product type onboarding.
- Use low-confidence defaults to create inaccurate product facts.

## 5. Core Objects

| Object | Definition |
| --- | --- |
| `ListingCandidate` | A mapped supplier product that may become an Amazon listing. |
| `ReviewedProductContent` | Generated title, bullets, description, search terms, and enriched attributes after deterministic and LLM review. |
| `ContentReviewResult` | Reviewer verdict, scores, issues, revision instructions, and manual review fields. |
| `AttributeResolution` | One Amazon attribute value plus evidence, source, confidence, and state. |
| `ListingPlan` | A complete SP-API submission plan with product type, attributes, offer, images, variation, and audit metadata. |
| `ValidationFeedback` | Normalized Amazon validation preview, PUT, or GET issue. |
| `ManualReviewItem` | A blocking or low-confidence item requiring human confirmation. |

## 6. Main Flow

```text
Giga sync / local product data
  -> ListingCandidate selection
  -> StandardProduct normalization
  -> Content Generator LLM
  -> Deterministic compliance scan
  -> Content Reviewer LLM
       -> pass: save ReviewedProductContent
       -> revise: regenerate with reviewer feedback, max N attempts
       -> reject/manual_review: stop listing flow
  -> Product Type Definitions schema sync/cache
  -> Attribute Resolver
  -> Attribute coverage report
  -> Commercial Gate
  -> Image Gate
  -> Variation Resolver
  -> Quality Gate
  -> Strict dry-run VALIDATION_PREVIEW
  -> LIVE putListingsItem
  -> getListingsItem confirmation
  -> ValidationFeedback persistence
```

## 7. Content Review State Machine

```text
not_generated
  -> generated
  -> deterministic_failed
  -> llm_review_passed
  -> llm_review_revision_requested
  -> regenerated
  -> manual_review_required
  -> rejected
```

Rules:

- Only `llm_review_passed` content can enter Attribute Resolver and API listing submission.
- `deterministic_failed` can be auto-sanitized once when safe.
- `llm_review_revision_requested` may loop back to generation up to the configured retry limit.
- `manual_review_required` and `rejected` must not be silently converted into publishable content.

## 8. Attribute Resolution State Machine

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

- Required attributes cannot proceed to LIVE in `unresolved`, `resolved_low_confidence`, or `needs_manual_review`.
- Recommended and AI enrichment attributes can proceed with warnings if unresolved.
- Amazon issues create `ValidationFeedback` and should be queryable by product type, attribute, issue code, source rule, and SKU.

## 9. Module Boundaries

| Module | Responsibility |
| --- | --- |
| `ProductContentGenerator` | Generate candidate content and enriched attributes. |
| `ProductContentReviewer` | Review content accuracy, policy, and Amazon readiness. |
| `ComplianceClaimScanner` | Deterministic high-risk policy scan and safe sanitization. |
| `AmazonSchemaService` | Product Type Definitions cache and schema inspection. |
| `AttributeRuleLoader` | Load product-type mapping rules from config. |
| `AttributeResolver` | Resolve Amazon attributes from facts, reviewed enrichment, derived values, defaults, and manual confirmations. |
| `AttributePayloadRenderer` | Render resolved values into Listings Items API attribute shapes. |
| `AmazonListingAttributeCoverageGate` | Compare schema required attributes with rendered payload and block missing or low-confidence required coverage before submitter. |
| `AmazonListingCommercialGate` | Price/inventory decision and audit. |
| `AmazonVariationResolver` | Parent/child structure and variation attribute uniqueness. |
| `AmazonListingQualityGate` | Final local blocking checks before Amazon API. |
| `AmazonListingSubmitter` | Existing listing check, validation preview, PUT, confirmation, and feedback persistence. |

## 10. Data Ownership

| Asset | Owner |
| --- | --- |
| Product raw sync tables | Giga sync module |
| `ds_api_product_details` content rows | Content generation/review module |
| Attribute rules config | Attribute resolution module |
| Product Type schema cache | `AmazonSchemaService` |
| API submission audit | `AmazonListingSubmitter` |
| Commercial gate audit | `AmazonListingCommercialGate` |
| Variation audit | `AmazonVariationResolver` |
| Manual review queue | Listing workflow module |

No module should bypass another module's repository or mutate another module's state without an explicit API or repository boundary.

## 11. Quality Gates

| Gate | Blocking Condition |
| --- | --- |
| Content deterministic scan | Unsupported pesticide/device/medical/antimicrobial claim remains after safe sanitization. |
| LLM content review | Unsupported factual claim, Amazon policy issue, severe quality issue, or low accuracy score. |
| Attribute coverage gate | Schema required attribute is missing from rendered payload, or resolved with low confidence. |
| Commercial gate | Unsafe price, stale data, invalid currency, insufficient margin, or inventory policy failure. |
| Variation resolver | No unique or allowed variation theme and no approved fallback. |
| Amazon validation preview | Amazon returns blocking issues. |
| LIVE confirmation | PUT accepted but GET confirms unresolved listing issues. |

## 12. Development Decisions

| Topic | Decision |
| --- | --- |
| LLM review failure handling | `pass` proceeds; `revise` triggers one automatic regeneration with reviewer feedback; repeated failure becomes `manual_review` or `reject`; `manual_review` and `reject` do not enter listing flow. |
| Reviewer strictness | Required factual uncertainty is treated as `manual_review`; copy quality issues are `revise`; unsupported facts, pesticide/device/medical/antimicrobial claims, or invented certifications are `reject`. |
| Inventory publish cap | Listing creation clamps publish quantity to category `max_publish_quantity`, records `source_quantity`, `publish_quantity`, rule version, and evidence. Invalid/stale inventory still blocks. |
| Strict dry-run | Default dry-run is offline. Strict dry-run is explicit and may call Amazon read/validation APIs, but never PUT. |
| Default attributes | Defaults must carry evidence and confidence. Low-confidence required defaults block LIVE. |

## 13. CLI/API Contract Direction

Primary listing entry:

```bash
python main.py --task generate-listing-api --category CABINET
python main.py --task generate-listing-api --category CABINET --strict-validation
python main.py --task generate-listing-api --category CABINET --sku meow... --strict-validation
python main.py --task generate-listing-api --category CABINET --sku-file /path/to/skus.txt --only-not-on-amazon --strict-validation
python main.py --task generate-listing-api --category CABINET --no-dry-run
```

Scope filters:

```bash
--sku meow...
--sku-file /path/to/skus.txt
--only-not-on-amazon
```

Deprecated:

```bash
python main.py --task generate-listing
```

The deprecated command may remain as a dry-run alias temporarily, but it must not generate Excel workbooks.

## 14. Review Output Contract

```json
{
  "verdict": "pass",
  "accuracy_score": 0.95,
  "compliance_score": 1.0,
  "amazon_readiness_score": 0.92,
  "issues": [],
  "revision_instructions": "",
  "manual_review_fields": [],
  "reviewed_fields": ["title", "bullet_1", "bullet_2", "description"],
  "unsupported_claims": []
}
```

Allowed verdicts:

- `pass`
- `revise`
- `manual_review`
- `reject`

## 15. Phase 1 Acceptance

- `generate-listing-api` is the only menu-visible new listing path.
- `generate-listing` no longer generates Excel workbooks.
- Content generation has deterministic scan + LLM review + bounded regeneration.
- Review metadata is persisted in `ds_api_product_details.raw_json`.
- Attribute Resolver design supports CABINET and OTTOMAN without new category-specific builder branches.
- CABINET test report failures can be represented as coverage and validation feedback, not just log text.
- CLI unit tests and targeted service tests pass.
