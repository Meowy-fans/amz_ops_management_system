# CHAIR Parent Dimension Shape Fix — Production Deploy

**Date**: 2026-06-28  
**Image**: `amz-listing-management-system:2026-06-28-chair-parent-dims-fix`  
**Base**: `amz-listing-management-system:2026-06-28-category-rule-lifecycle`

## Change

Fix Amazon `4000001` on variation parents: `OptionalRuleChildrenEnricherV2` no longer wraps
object-embedded `shape: measure` children (e.g. `item_depth_width_height.depth`) as
`[{unit,value}]` arrays. Only YAML `measure_array` children (e.g. `seat.height`) are wrapped.
Existing populated child fields are not overwritten.

Files:
- `src/services/optional_rule_children_enricher_v2.py`
- `config/.../chair.yaml` (`seat.depth` / `seat.height` → `measure_array`)
- `config/.../ottoman.yaml` (`seat.height` → `measure_array`)

## Deploy

```bash
cd /data/docker-compose/amz-listing-management-system
docker compose build
docker compose up -d
```

| Check | Result |
| --- | --- |
| `docker compose ps` | Main container **healthy**; 3 schedulers **Up** |
| Enricher fix in image | Present |
| `list-categories` | 16 categories returned |

## Production regression (CHAIR 18 SKU, `--engine v2 --strict-validation`)

| Metric | Before fix | After deploy |
| --- | --- | --- |
| `validation_preview_passed` | 12/18 | **14/18** |
| Parent `4000001` | `PARENT-08E9DEF253B2` failed | `PARENT-86D437990817` **passed** (0 issues) |
| Remaining issues | HTML/dims/review | Same classes (Epic 外 + `included_components` review) |

## Verification commands

```bash
docker exec amz-listing-management-system python main.py --task list-categories

docker exec amz-listing-management-system python main.py --task generate-listing-api \
  --category CHAIR --sku <18-SKU-list> \
  --strict-validation --only-not-on-amazon --engine v2
```

## Notes

- No DB migration required.
- `--engine v2 --no-dry-run` LIVE PUT remains blocked.
