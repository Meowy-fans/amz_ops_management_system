# Category Rule Lifecycle — Production Deploy & BED_FRAME E2E

**Date**: 2026-06-28  
**Image**: `amz-listing-management-system:2026-06-28-category-rule-lifecycle`  
**Migration**: `013_amz_listing_pending_rule_review` (head)

## Deploy

- Built and deployed via `/data/docker-compose/amz-listing-management-system/`
- All 4 containers healthy on new image tag
- Alembic upgraded: `012` → `013`

## Promote executed (2026-06-28)

- **CHAIR** promoted to `mode: live_eligible` (2026-06-28) — S7 18/18 offline + 14/18 preview; backup `chair.yaml.bak.20260628_010219`
- **TABLE** promoted to `mode: live_eligible` (2026-06-28) — S7 4/4 offline + 4/4 preview; backup `table.yaml.bak.20260628_005734`
- **BED_FRAME** promoted to `mode: live_eligible` via `promote-category-rules-v2 --no-dry-run`
- Backup: `bed_frame.yaml.bak.20260628_005410` (in container config dir)
- Reviewer audit: `cursor@production`

## TABLE YAML restored

- Restored from `2026-06-27-rule-authoring-v2-bed-frame-preview` image (301 lines)
- S7 re-run: offline **4/4**, preview **4/4** — ready for promote when operator chooses

## Incident: bed_frame.yaml restore

First deploy picked up a corrupted local `bed_frame.yaml` (`attributes: {}`, from a prior unit-test writeback).
Restored 835-line file from previous image `2026-06-27-rule-authoring-v2-bed-frame-preview` and rebuilt.

## BED_FRAME lifecycle E2E (production container)

### Layer 1 review

```
leaf_count=47 placeholder_leaves=0 review_items=5 blocking_items=0
```

5 info-level `inherited_source` only (from TABLE reuse); no blocking items.

### S7 acceptance (`--preview BED_FRAME`)

| KPI | Result |
| --- | --- |
| Offline zero missing | **4/4** |
| Preview passed | **3/4** |
| Passed SKUs | meow25110896fzS, meow251108VJprf, meow260518aoxYQ |
| Failed SKU | meow251108FetOX — `validation_preview_issues` (1 amazon issue, content/HTML) |

Full JSON: `docs/test-reports/2026-06-28-bed-frame-lifecycle-e2e.json`

### Promote gate (dry-run)

```bash
python3 main.py --task promote-category-rules-v2 --category BED_FRAME \
  --require-preview --min-preview-passed 1 \
  --acceptance-file docs/test-reports/2026-06-28-bed-frame-lifecycle-e2e.json
```

**Result**: `status=go` — all required checks passed. Not promoted (`dry_run` preserved).

### Feedback triage

```bash
python3 main.py --task analyze-listing-feedback-v2 --category BED_FRAME --limit 20
```

| Route | Code | Count | Notes |
| --- | --- | --- | --- |
| rule_layer | 90220 | 68 | learn → approve |
| rule_layer | 99022 | 8 | omit_suggestions: merchant_suggested_asin |
| content_layer | 100339 | 3 | product_description — content pipeline |

## Fix shipped in this deploy

- `task_dispatcher.py` missing imports for `promote-category-rules-v2`, `onboard-category-v2`, `analyze-listing-feedback-v2`, `approve-rule`

## Next steps (operator)

1. Fix `meow251108FetOX` product_description HTML (Layer 2/content) for 4/4 preview
2. Waive or review inherited_source items if desired
3. When ready: `promote-category-rules-v2 --no-dry-run --reviewer ...` (still dry_run until explicit promote)
