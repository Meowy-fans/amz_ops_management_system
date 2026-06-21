# API-native Listing Quality Production Deployment

- **Date**: 2026-06-15
- **Environment**: production compose `/data/docker-compose/amz-listing-management-system/`
- **Image**: `amz-listing-management-system:2026-06-15`
- **Scope**: `EPIC-AMZ-LISTING-API-NATIVE-QUALITY`
- **Deployment command**: `./deploy/production/deploy.sh`

## Summary

The API-native multi-category listing quality Epic was deployed to production. The main service and all scheduled sidecars were rebuilt on image `amz-listing-management-system:2026-06-15`.

## Containers

| Container | Image | Result |
| --- | --- | --- |
| `amz-listing-management-system` | `amz-listing-management-system:2026-06-15` | Running, healthy |
| `amz-price-inventory-scheduler` | `amz-listing-management-system:2026-06-15` | Running |
| `amz-order-sync-scheduler` | `amz-listing-management-system:2026-06-15` | Running |
| `amz-order-daily-report-scheduler` | `amz-listing-management-system:2026-06-15` | Running |

## Smoke Checks

| Check | Result |
| --- | --- |
| Public route `https://amz-listing.meowy.fans` | HTTP 302 to SSO login |
| `list-categories` | Returned `CABINET` and `HOME_MIRROR` |
| Legacy `generate-listing --category CABINET` | Printed deprecation notice and forwarded to API-native dry-run |
| Legacy Excel generation | Not executed; no Excel new-listing flow used |
| OTTOMAN strict dry-run | 1 parent `validation_preview_passed`, 2 child `skipped_existing`, issues=0 |
| PUT during strict dry-run | None |

## Price / Inventory Scheduler Check

The post-deploy hourly price/inventory scheduler started automatically and completed one production cycle.

| Stage | Result |
| --- | --- |
| Delayed confirmation | 1 record, `delayed_update_confirmed=1` |
| Giga price sync | 409 total, 348 valid/saved, 0 failed |
| Giga inventory sync | 409/409 updated |
| Local pricing | 458 processed, 408 updated, 50 skipped for missing cost |
| Amazon price/inventory update | 273 SKUs processed |
| Amazon update summary | 269 `skipped_no_change`, 4 `blocked_listing_issue`, failed=0 |

Blocked listing issue SKUs:

| SKU | Issue |
| --- | --- |
| `meow251115t1oiT` | Amazon `99300`, product description policy issue |
| `meow251108qMxfi` | Amazon `99300`, product description policy issue |
| `meow2508242n63Y` | Amazon `99300`, product description policy issue |
| `meow251115Gb5dN` | Amazon `18503`, pesticide/pesticide-device qualification issue |

## Documentation Updated

- `/data/README.md`
- `/data/TODO.md`
- `README.md`
- `STATUS.md`
- `TODO.md`
- `deploy/production/README.md`
- `docs/epics/api-native-listing-quality-pipeline.md`

## Conclusion

Production deployment is accepted. API-native listing creation remains dry-run by default, strict validation uses Amazon `VALIDATION_PREVIEW` without PUT, and LIVE listing submission remains behind explicit `--no-dry-run` plus local quality gates.
