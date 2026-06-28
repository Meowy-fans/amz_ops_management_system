# Listing Payload Engine V2 Production Deploy - 2026-06-27

## Image

`amz-listing-management-system:2026-06-27-listing-payload-v2`

Built from workspace at `/home/liangqinhao/amz_listing_management_system` with
base image `2026-06-25-confidence-review-pipeline`.

## Deploy

```bash
cd /data/docker-compose/amz-listing-management-system
docker compose up -d
```

All four services recreated on the new image:

- `amz-listing-management-system`
- `amz-price-inventory-scheduler`
- `amz-order-sync-scheduler`
- `amz-order-daily-report-scheduler`

## Production Smoke

| Check | Result |
| --- | --- |
| `docker compose ps` | Main container `healthy`; 3 schedulers `Up` |
| `list-categories` | 16 categories returned |
| `evaluate-listing-v2-validation-compare` | `status=go` (3/3) inside production container, no workspace mount |

## Non-existing SKU Evidence (pre-deploy container run)

| Scope | Result |
| --- | --- |
| OTTOMAN `meow2511088jSUW` + `meow260518LZZCw` variation family | New parent `PARENT-B44F29098D69` → `validation_preview_passed` (0 issues); children `skipped_existing` |
| CABINET explicit SKUs with `--only-not-on-amazon` | Pool largely on Amazon now (`skipped_existing_scope`) |

## Guardrails Unchanged

- `generate-listing-api --engine v2 --no-dry-run` → blocked
- Default listing engine remains V1 for LIVE PUT

## Ops Docs Updated

- `/data/README.md`
- `/data/TODO.md`
