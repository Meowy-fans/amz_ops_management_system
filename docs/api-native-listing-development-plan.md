# API-native Listing Development Plan

> Status: Draft
> Date: 2026-06-13
> Related design: `docs/api-native-listing-system-design.md`, `docs/module-design/api-attribute-resolution.md`

## Development Principles

- Follow TDD Module Closure: Red -> Green -> Integration -> Acceptance.
- Keep Excel listing code out of user-facing flows first; remove or move legacy modules only after API-native coverage is stable.
- Do not add category-specific Python branches for CABINET/HOME_MIRROR/OTTOMAN unless explicitly marked as temporary compatibility code.
- Treat Amazon `VALIDATION_PREVIEW` as authoritative pre-submit feedback.
- Treat LLM as a generator/reviewer, not a fact source.

## Confirmed Defaults

| Topic | Default |
| --- | --- |
| Content review retries | One automatic regeneration after reviewer `revise`. |
| Reviewer policy | Conservative: uncertain required facts go to manual review; unsupported claims reject. |
| Inventory cap | Clamp publish quantity to category max for listing creation and audit both source/publish quantities. |
| Strict dry-run | Explicit opt-in; offline dry-run remains default. |
| Defaults | Must include evidence/confidence; low-confidence required fields block LIVE. |

## Phase 0: Entry-point Cleanup

Goal: remove Excel listing flow from operations noise.

Tasks:

1. Route menu option `1.8` to `generate-listing-api`.
2. Make `generate-listing` a deprecated dry-run alias.
3. Remove template update/correction from interactive menu.
4. Update README, STATUS, TODO.

Acceptance:

- CLI menu exposes API-native listing only.
- `generate-listing` prints a deprecation notice and does not generate `.xlsm`.
- CLI tests pass.

Current status: in progress.

## Phase 1: Content Review Gate

Goal: generated listing content cannot feed API listing until it passes deterministic and LLM review.

New modules:

- `src/services/product_content_reviewer.py`
- `tests/unit/services/test_product_content_reviewer.py`

Implementation:

1. Add `ContentReviewIssue` and `ContentReviewResult` dataclasses.
2. Add reviewer prompt under `config/api_clients/deepseek.yaml`.
3. `ProductContentReviewer.review(product, product_type, content)` returns structured verdict.
4. `ProductContentGenerator.generate()` or `ProductDetailGenerationService.process_single_sku()` runs:
   - deterministic scanner
   - reviewer LLM
   - bounded revision loop, max 1 automatic regeneration
5. Persist review metadata in `raw_json`.
6. Block saving publishable content unless verdict is `pass`.

Tests:

- Reviewer parses valid JSON.
- Reviewer handles malformed JSON as `manual_review`.
- Pesticide/mold/mildew claims fail or revise.
- Unsupported material/function claim fails review.
- Pass case persists review metadata.
- Revision loop stops at max attempts.

Acceptance:

- Only `llm_review_passed` content can enter listing flow.
- Existing compliance scanner remains deterministic first line of defense.

## Phase 2: Attribute Resolver v1

Goal: replace category-specific payload hardcode with schema/config-driven resolution.

New modules:

- `src/services/attribute_rule_loader.py`
- `src/services/attribute_resolver.py`
- `src/services/attribute_payload_renderer.py`
- `config/amz_listing_data_mapping/api_attribute_rules/cabinet.yaml`
- `config/amz_listing_data_mapping/api_attribute_rules/ottoman.yaml`

Implementation:

1. Define rule config contract.
2. Implement source path reader for:
   - `normalized.*`
   - `raw.*`
   - `content.*`
   - `content.enriched_attributes.*`
   - defaults
3. Implement transforms:
   - text
   - list_value
   - enum
   - boolean_yes_no
   - integer
   - dimension_object
   - measure
4. Produce per-field `AttributeResolution`.
5. Render Listings Items API attribute JSON.
6. Keep `AmazonListingPayloadBuilder` as thin compatibility wrapper.

Tests:

- Source priority.
- Enum alignment using schema valid values.
- Default evidence and confidence.
- Required low confidence blocks.
- CABINET required field coverage from the 2026-06-11 test report.
- OTTOMAN regression payload fields.

Acceptance:

- CABINET and OTTOMAN use resolver path.
- No new CABINET-specific branches are added to builder.
- Coverage report shows required/recommended/AI enrichment fill rates.

## Phase 3: Strict Dry-run with Amazon Validation Preview

Goal: make dry-run reflect Amazon's authoritative validation without PUT.

Status: implemented on 2026-06-13 for `generate-listing-api --strict-validation`.

Implementation:

1. Add CLI option `--strict-validation` or env `LISTING_STRICT_VALIDATION=true`.
2. In strict dry-run, run existing listing check + `VALIDATION_PREVIEW`.
3. Persist preview issues in `amazon_api_submissions` with status `validation_preview_issues` or `validation_preview_passed`.
4. Keep raw preview issues in submission audit for the first implementation.
5. Normalize issues into `ValidationFeedback` shape in the SKU audit/report phase.
6. CLI summary separates:
   - content blocked
   - attribute blocked
   - commercial blocked
   - variation blocked
   - quality blocked
   - validation preview issues
   - validation preview passed

Tests:

- Strict dry-run calls validation preview but not PUT.
- Amazon issues are persisted.
- Non-strict dry-run remains offline by default.
- Existing listing check behavior is explicit and testable.

Acceptance:

- CABINET 18-SKU dry-run can produce actionable Amazon issue report before LIVE.

## Phase 4: Candidate Scope and Observability

Goal: make production tests focused and auditable.

Status: scope controls and status audit summary implemented on 2026-06-14; inventory clamp and richer exported acceptance reports remain follow-up work.

Implementation:

1. Add `--sku` and `--sku-file`.
2. Add `--only-not-on-amazon`.
3. Change listing-creation inventory over-cap behavior from hard block to clamp with audit evidence.
4. Persist pre-submit blocks in a unified audit table or as submission audit rows.
5. Add coverage/audit export command.
6. Fix `sync-products` final stats printing bug.

Tests:

- SKU filter limits plans.
- SKU file limits plans.
- Only-not-on-Amazon performs read-only check.
- Pre-submit block is queryable.

Acceptance:

- Operator can rerun the exact 18-SKU CABINET test set without processing the whole category.

## Phase 5: Legacy Excel Retirement

Goal: remove dead operational code after API-native path is stable.

Implementation:

1. Move Excel-only modules under a legacy namespace or delete after test replacement.
2. Replace old product-listing-service design doc.
3. Remove old Excel generation tests once API-native integration tests cover the same business path.
4. Keep template parsing only if needed for migration tooling.

Acceptance:

- No menu, README, production script, or primary test relies on Excel listing generation.
- Remaining legacy code is clearly isolated.

## Suggested Execution Order

1. Finish Phase 0 and run CLI tests.
2. Implement Phase 1 content review gate.
3. Implement Phase 2 resolver using CABINET and OTTOMAN fixtures.
4. Implement Phase 3 strict validation preview.
5. Rerun CABINET 18-SKU test in strict dry-run.
6. Decide inventory clamp vs block policy before LIVE retry.
