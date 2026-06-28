# SOFA V2 Coverage Rules Production Deploy - 2026-06-27

## Image

`amz-listing-management-system:2026-06-27-sofa-v2-coverage-rules`

Built from workspace at `/home/liangqinhao/amz_listing_management_system`.

## Changes In This Slice

- Universal preset `product_description` fallback via `text_join` (`content.bullets`)
- SOFA YAML: `seating_capacity` maps Giga `Seats`, `sofa_type` uses title `enum_scan`
- SOFA `seat.fill_material` uses schema `enum` token (`foam`)
- Shared transforms: `parse_integer_value`, `join_text_value`, `scan_enum_token`

No SKU-level hard coding.

## Deploy

```bash
cd /data/docker-compose/amz-listing-management-system
docker compose build
docker compose up -d
```

All four services recreated on the new image.

## Production Smoke

| Check | Result |
| --- | --- |
| `docker compose ps` | Main container `healthy`; 3 schedulers `Up` |
| `list-categories` | 16 categories returned |
| `evaluate-listing-v2-validation-compare` | `status=go` (3/3), no workspace mount |
| SOFA `meow25110865jrz` `--engine v2 --strict-validation --only-not-on-amazon` | `validation_preview_passed` (0 issues) |
| `generate-listing-api --engine v2 --no-dry-run` | blocked (`v2_engine_requires_dry_run`) |

## Remaining SOFA Notes

- `meow251108rFGvX` / `meow251108W6Ryf` pass V2 coverage but strict-preview still has width>82in Amazon WARNING (business/compliance, Epic 外)
- LIVE `--engine v2 --no-dry-run` remains blocked

## Ops Docs Updated

- `/data/README.md`
- `/data/TODO.md`
