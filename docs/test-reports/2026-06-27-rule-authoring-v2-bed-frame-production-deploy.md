# Rule Authoring V2 — BED_FRAME Production Deploy — 2026-06-27

- Image: `amz-listing-management-system:2026-06-27-rule-authoring-v2-bed-frame`
- Compose: `/data/docker-compose/amz-listing-management-system/docker-compose.yml`

## Included changes

- `bed_frame.yaml` v2 (4-SKU dry-run pool)
- `EvidenceResolverV2` boolean `False` enum fix + country ISO normalization (from prior pass)
- `review-pending-rules` CLI (S5 read-only)
- `item_length_width_height` dimension strategy support

## Smoke

| Check | Result |
| --- | --- |
| Main container | healthy |
| S6 golden regression | 4/4 PASS |
| BED_FRAME offline | 4/4 zero missing |
| BED_FRAME placeholder rate | 2.1% |

## Commands

```bash
cd /data/docker-compose/amz-listing-management-system
docker compose build
docker compose up -d
docker exec -w /app amz-listing-management-system python3 scripts/s6_golden_regression.py
docker exec -w /app amz-listing-management-system python3 scripts/s7_rule_authoring_acceptance.py BED_FRAME
```

## Reports

- `docs/test-reports/2026-06-27-bed-frame-rule-authoring-pipeline.md`
- Prior: TABLE / S6 / S7 acceptance reports
