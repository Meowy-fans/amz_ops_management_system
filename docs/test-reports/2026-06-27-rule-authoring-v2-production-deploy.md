# Listing Rule Authoring V2 Production Deploy — 2026-06-27

## Image

`amz-listing-management-system:2026-06-27-rule-authoring-v2`

Built from workspace `/home/liangqinhao/amz_listing_management_system`.

## Changes In This Slice

### Rule Authoring pipeline (Epic S0–S4, S6–S7)

- `rule_skeleton_generator_v2.py` + `generate-rule-skeleton-v2`
- `rule_field_mapper_v2.py` + `map-rule-fields-v2`
- `rule_pattern_reuse_v2.py` + `reuse-rule-patterns-v2`
- `rule_feedback_adapter_v2.py` + `learn-rules-from-feedback-v2`
- `rule_migration_v2.py` + `migrate-rules-v2` / `evaluate-rules-v2-golden`
- `optional_rule_children_enricher_v2.py` (90220 preview optional children)
- `rule_tree_utils_v2.py`
- Acceptance scripts: `s6_golden_regression.py`, `s7_rule_authoring_acceptance.py`

### CHAIR rules

- `config/.../api_attribute_rules/chair.yaml` — quick-validation V2 rules
  (`dimension_strategy`, nested `frame`/`seat`/`item_depth_width_height`, enricher paths)

### Docs

- ADR `ADR-2026-06-27-listing-rule-authoring-v2.md`
- Reports: S6 golden, S7 acceptance

Live categories (SOFA/CABINET/HOME_MIRROR/OTTOMAN) YAML **unchanged** on disk;
S6 migration is no-op for `live_eligible` attributes.

## Deploy

```bash
cd /data/docker-compose/amz-listing-management-system
docker compose build
docker compose up -d
```

All four services recreated on `2026-06-27-rule-authoring-v2`.

## Production Smoke

| Check | Result |
| --- | --- |
| `docker compose ps` | Main container `healthy`; 3 schedulers `Up` |
| `list-categories` | 16 categories |
| `evaluate-rules-v2-golden` | `status=go` 4/4 |
| `evaluate-listing-v2-validation-compare` | `status=go` 3/3 |
| CHAIR `meow2511081Gqqd` `validate-listing-v2` | `validation_preview_passed` |
| SOFA `meow25110865jrz` `validate-listing-v2` | `validation_preview_passed` |
| `generate-listing-api --engine v2 --no-dry-run` | blocked (`v2_engine_requires_dry_run`) |

## Ops Notes

- No database migration required for this slice
- CHAIR remains `mode: dry_run` in `chair.yaml`
- `--engine v2 --no-dry-run` LIVE cutover still intentionally blocked

## Ops Docs Updated

- `/data/README.md` (image tag)
- `STATUS.md`
