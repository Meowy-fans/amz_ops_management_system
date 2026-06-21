# Required Attribute Coverage Gate Test Report

> Date: 2026-06-15  
> Task: TASK-137 Required Attribute Coverage Gate  
> Scope: API-native listing plan construction before Amazon submitter

## Background

HOME_MIRROR live listing creation exposed a repeatable failure mode: Amazon
Product Type Definitions marked `fabric_type` as required, but the payload did
not include it because the previous builder fallback was CABINET-specific.

The broader system issue is any future product type can contain Amazon-required
attributes that are weakly related to supplier facts. These attributes must be
resolved by config with evidence, or blocked locally before Amazon submission.

## Changes Validated

- Added `AmazonListingAttributeCoverageGate`.
- `ProductListingAPIPlanBuilder` now evaluates schema required coverage after
  rendering each plan and before sending plans to `AmazonListingSubmitter`.
- Missing or low-confidence required attributes return
  `blocked_attribute_coverage`.
- `fabric_type` fallback is now owned by YAML rules for CABINET, HOME_MIRROR,
  and OTTOMAN instead of a dedicated payload-builder method.
- `AmazonListingPayloadBuilder` now returns `attribute_resolutions` for coverage
  audit and no longer owns `_set_fabric_type`.

## Test Evidence

```bash
.venv/bin/pytest \
  tests/unit/services/test_amazon_listing_attribute_coverage_gate.py \
  tests/unit/services/test_amazon_listing_payload_builder.py \
  tests/unit/services/test_product_listing_service.py \
  tests/unit/services/test_amazon_listing_quality_gate.py -q
```

Result:

```text
45 passed
```

Full regression:

```bash
.venv/bin/pytest -q
git diff --check
```

Result:

```text
Full pytest passed
git diff --check passed
```

Target behavior covered:

- Required attributes present in payload pass coverage.
- Missing required attributes block locally with
  `MISSING_REQUIRED_ATTRIBUTE_RULE`.
- Schema lookup failures fail open with `ATTRIBUTE_SCHEMA_UNAVAILABLE` warning.
- Low-confidence required resolutions block locally.
- Evidenced medium/high confidence defaults pass.
- HOME_MIRROR with no supplier material uses YAML fallback
  `Glass, Metal`.
- A synthetic product type with required `fabric_type` but no YAML rule returns
  `blocked_attribute_coverage` and does not produce a submittable plan.

## Production Deployment

Image: `amz-listing-management-system:2026-06-15-required-coverage`

Deployment command:

```bash
docker compose config --quiet
/home/liangqinhao/amz_listing_management_system/deploy/production/deploy.sh
```

Post-deploy smoke:

- Main container healthy.
- Scheduler sidecars running:
  - `amz-price-inventory-scheduler`
  - `amz-order-sync-scheduler`
  - `amz-order-daily-report-scheduler`
- Public route `https://amz-listing.meowy.fans` returns SSO 302.
- `list-categories` returns `CABINET` and `HOME_MIRROR`.

Production HOME_MIRROR strict dry-run:

```bash
docker exec amz-listing-management-system python main.py \
  --task generate-listing-api \
  --category HOME_MIRROR \
  --strict-validation \
  --only-not-on-amazon
```

Result:

```text
blocked_variation_resolution: 7
skipped_existing_scope: 12
validation_preview_issues: 6
```

The six validation preview plans each returned 15 Amazon issues. Latest
submission inspection confirmed:

```text
missing_required=0
fabric_related=[]
```

The original `fabric_type` missing-required blocker is therefore closed in
production. Remaining HOME_MIRROR validation issues are separate attribute
mapping work.

## Residual Risk

HOME_MIRROR still cannot be treated as LIVE-ready because Amazon
`VALIDATION_PREVIEW` returns 15 non-required issues per generated plan. These
should be triaged as a follow-up mapping task before retrying `--no-dry-run`.
