# EPIC: API-native Multi-category Listing Quality Pipeline

> Epic ID: `EPIC-AMZ-LISTING-API-NATIVE-QUALITY`
> Status: Completed
> Date: 2026-06-13
> Completed: 2026-06-15
> Production Deployed: 2026-06-15
> Owner: amz-listing-management-system

## 1. Background

The 2026-06-11 CABINET API listing E2E test proved that the SP-API listing path can execute end to end, but also exposed a system-level gap: local dry-run and quality gates did not match Amazon's authoritative validation, and API payload construction was too shallow for CABINET.

This is not a single-category bug. Future listing operations will cover many product types, so the fix must upgrade the listing quality pipeline itself.

## 2. Epic Goal

Build an API-native, multi-category listing quality pipeline that can create Amazon listings with accurate content, rich structured attributes, Amazon validation feedback, and auditable quality decisions without relying on Excel upload files or category-specific Python hardcode.

## 3. In Scope

- Deprecate Excel new listing operations.
- Make `generate-listing-api` the only new listing creation entry point.
- Add LLM content review gate:
  - Generator LLM creates listing content.
  - deterministic scanner catches high-risk claims.
  - Reviewer LLM checks factual accuracy, Amazon readiness, and policy risks.
- Build Attribute Resolver v1:
  - Product Type Definitions schema driven.
  - config-driven product-type mapping rules.
  - evidence/confidence per attribute.
  - coverage report.
- Add strict dry-run with Amazon `VALIDATION_PREVIEW`.
- Persist and normalize Amazon validation feedback.
- Add SKU-level test scope controls.
- Independently validate with:
  - CABINET 18-SKU test set from `docs/test-reports/2026-06-11-cabinet-api-listing-e2e.md`
  - OTTOMAN regression from `docs/acceptance/ottoman-e2e-2026-05-18.md`

## 4. Out of Scope

- Giga automatic order placement.
- Shipment tracking and Amazon `confirmShipment`.
- Order sync and order notification.
- Price/inventory hourly update scheduler.
- PPC, profit analysis, lifecycle analytics.
- Broad Web UI redesign.
- General marketplace abstraction beyond Amazon.

## 5. Work Breakdown

| Task | Title | Status | Acceptance |
| --- | --- | --- | --- |
| TASK-123 | Deprecate Excel listing entry | Done | Menu and README expose API-native listing only; `generate-listing` does not generate `.xlsm`. |
| TASK-126 | LLM content review gate | Done | Content must pass deterministic scanner and Reviewer LLM before it can feed listing. |
| TASK-124 | Attribute Resolver Phase 1 | Done | CABINET and OTTOMAN attributes are resolved through schema/config rules, not builder hardcode. |
| TASK-125 | Strict dry-run + validation preview | Done | Dry-run can call Amazon `VALIDATION_PREVIEW` without PUT and persist issues. |
| TASK-128 | SKU scope controls and audit summary | Done | `--sku`, `--sku-file`, and `--only-not-on-amazon` support targeted reruns and status audit summaries. |
| TASK-129 | CABINET 18-SKU strict dry-run acceptance | Done, superseded by fixes | Initial strict dry-run produced scope, gate, and Amazon validation results; P0 schema gaps were closed by TASK-132, TASK-133, and TASK-134. |
| TASK-130 | OTTOMAN regression acceptance | Done | Existing OTTOMAN success path remains green through API-native resolver path; strict dry-run parent validation preview passed with 0 issues. |
| TASK-131 | Excel legacy retirement | Done | Excel-only modules and legacy listing entry functions have script-visible `@retire` markers and an independent retirement plan with a 2026-07-31 removal window. |
| TASK-132 | CABINET strict validation P0 fixes | Done | Fixed `door`, variation theme valid value, dimension/weight unit, and inapplicable attributes; Amazon preview ERROR is now zero for unblocked plans. |
| TASK-133 | CABINET remaining business blockers | Done | Commercial quantity cap now clamps with audit; parent quantity is 0; variation item_width and country issues are fixed; remaining CABINET blockers are business decisions. |
| TASK-134 | CABINET 48in vanity product type / variation business decision | Done | CABINET width >42in remains allowed for strict dry-run evidence but is `live_blocking` before PUT; duplicate variation signatures remain fail-closed. |

## 6. Independent Acceptance Criteria

The Epic is complete only when all criteria below are met:

1. `generate-listing-api` is the only menu-visible and documented new listing entry.
2. `generate-listing` prints a deprecation notice and does not generate Excel workbooks.
3. Content generation includes deterministic scanner + Reviewer LLM.
4. Content that fails review cannot enter Attribute Resolver or API submission.
5. CABINET and OTTOMAN attribute construction use Attribute Resolver.
6. No new product-type hardcode is added to `AmazonListingPayloadBuilder`.
7. Strict dry-run supports Amazon `VALIDATION_PREVIEW` without PUT.
8. Amazon validation issues are persisted and queryable as feedback.
9. CABINET 18-SKU test set can be rerun without processing the whole category.
10. CABINET strict dry-run report shows:
    - content review result
    - attribute coverage
    - commercial gate result
    - variation gate result
    - quality gate result
    - Amazon validation preview result
11. OTTOMAN regression remains green.
12. Targeted unit/integration tests pass.
13. `STATUS.md`, `TODO.md`, and acceptance report are updated.

## 7. Production Acceptance

| Check | Result |
| --- | --- |
| Production image | `amz-listing-management-system:2026-06-15` |
| Main service | Healthy |
| Scheduled sidecars | Price/inventory, order sync, and daily report sidecars running |
| Public route | `https://amz-listing.meowy.fans` returns SSO redirect |
| Legacy listing entry | `generate-listing` prints deprecation notice and forwards to API-native dry-run |
| Strict dry-run smoke | OTTOMAN parent `validation_preview_passed`, child SKUs `skipped_existing`, no PUT |
| Price/inventory post-deploy cycle | 273 SKUs processed, failed=0 |

## 8. Implementation Decisions

These decisions are accepted as the default development contract for this Epic.

| Decision | Default |
| --- | --- |
| LLM review retry limit | One automatic regeneration after `revise`; a second failure becomes `manual_review` or `reject`. |
| Reviewer strictness | Conservative. Required factual fields with uncertainty become `manual_review`; ordinary copy quality issues become `revise`; clear unsupported claims become `reject`. |
| Inventory above publish cap | Clamp `publish_quantity` to `max_publish_quantity` for listing creation, while preserving `source_quantity` and clamp evidence in audit. Negative, missing, or stale inventory remains blocking. |
| Strict dry-run API usage | Offline dry-run remains default. Amazon `getListingsItem` and `VALIDATION_PREVIEW` run only when strict validation is explicitly enabled. |
| Attribute defaults | Defaults are allowed only with `confidence` and `evidence`. Low-confidence required attributes block LIVE. |

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| LLM reviewer gives false confidence. | Keep deterministic scanner and Amazon validation preview as hard gates. |
| Attribute defaults create inaccurate facts. | Require evidence/confidence and manual review for low-confidence required fields. |
| Scope grows into full UI workflow. | Keep Epic CLI/API-first; defer UI polish. |
| Excel removal breaks old tests. | Deprecate entry first, then isolate legacy code after replacement tests exist. |
| Amazon schema cache is stale. | Track schema fetch time/hash and allow forced refresh. |

## 10. Rollback / Safety

- Do not remove existing production listing audit tables.
- Do not delete Excel modules until API-native acceptance passes.
- Keep `generate-listing-api` dry-run default.
- LIVE submission remains behind `--no-dry-run`.
- Strict validation preview must not call PUT.

## 11. Related Documents

- `docs/api-native-listing-system-design.md`
- `docs/api-native-listing-development-plan.md`
- `docs/module-design/api-attribute-resolution.md`
- `docs/test-reports/2026-06-11-cabinet-api-listing-e2e.md`
- `docs/test-reports/2026-06-14-cabinet-18-strict-dry-run.md`
- `docs/test-reports/2026-06-15-ottoman-api-native-regression.md`
- `docs/test-reports/2026-06-15-api-native-quality-production-deploy.md`
- `docs/decisions/ADR-2026-06-15-cabinet-48in-live-policy.md`
- `docs/retirement/excel-listing-retirement-2026-06-15.md`
- `docs/acceptance/ottoman-e2e-2026-05-18.md`
