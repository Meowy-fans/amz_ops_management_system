# S6 Legacy Migration + Golden Regression — Listing Rule Authoring V2

- Date: 2026-06-27
- Epic: `EPIC-AMZ-LISTING-RULE-AUTHORING-V2`
- Module: `src/services/rule_migration_v2.py`
- Runner: `scripts/s6_golden_regression.py`

## Summary

S6 delivers conservative YAML migration (legacy full-block override + `live_eligible`
no-op on attributes) and golden regression that compares
`PayloadBuildPlan.attributes` before vs after in-memory migration.

**Golden regression: PASS (4 / 4)**

## Golden SKUs

| Product type | SKU | Attributes identical | Preview (post-check) |
| --- | --- | --- | --- |
| SOFA | `meow25110865jrz` | ✅ | `validation_preview_passed` |
| CABINET | `meow251115FC0ie` | ✅ | (offline golden only) |
| HOME_MIRROR | `meow251108CqW5i` | ✅ | (offline golden only) |
| OTTOMAN | `meow2511088jSUW` | ✅ | (offline golden only) |

## Migration policy

| Mode | Attribute merge behavior |
| --- | --- |
| `live_eligible` | **Preserve legacy `attributes` exactly**; skeleton-only schema attrs are not added (avoids live regression) |
| `dry_run` | Start from skeleton; each legacy attribute replaces the full top-level block (respects `AttributeRuleLoader` shallow-merge trap) |

Root keys preserved from legacy when present: `mode`, `version`, `presets`,
`dimension_strategy`, `post_processors`, `remove_attributes`, etc.

## Live category migration stats (in-memory)

| Category | Mode | Legacy attrs | Migrated attrs | Added |
| --- | --- | --- | --- | --- |
| SOFA | live_eligible | 24 | 24 | 0 |
| CABINET | live_eligible | 25 | 25 | 0 |
| HOME_MIRROR | live_eligible | 22 | 22 | 0 |
| OTTOMAN | live_eligible | 25 | 25 | 0 |

## TABLE dry-run expansion (illustrative)

`migrate-rules-v2 --category TABLE` (default dry-run) expands V1 flat YAML with
skeleton-only attributes while preserving legacy blocks — suitable for future TABLE
rule authoring pipeline; not written to disk in this acceptance run.

## CLI

```bash
# Golden regression (all default cases)
python3 main.py --task evaluate-rules-v2-golden

# Per category
python3 main.py --task evaluate-rules-v2-golden --category SOFA

# Migrate (dry-run default; add --no-dry-run to write with .pre_s6_migration backup)
python3 main.py --task migrate-rules-v2 --category TABLE

# Full script JSON report
docker exec -w /app amz-listing-management-system \
  python3 scripts/s6_golden_regression.py
```

Write is blocked when golden regression fails for that `live_eligible` category.

## Phase 2 gates (Epic)

| Gate | Result |
| --- | --- |
| SOFA preview-passed SKU unchanged | ✅ `meow25110865jrz` still passed |
| CABINET / HOME_MIRROR / OTTOMAN attributes identical | ✅ 3 / 3 |
| `live_eligible` mode unchanged | ✅ migration preserves `mode` |
| Full attribute blocks preserved | ✅ `live_eligible` uses legacy attrs only |

## Tests

`tests/unit/services/test_rule_migration_v2.py` — 4 passed

## Follow-ups

1. Run `migrate-rules-v2 --no-dry-run --category TABLE` when TABLE S1–S3 pipeline is ready
2. Rebuild production image to ship `rule_migration_v2.py` + CLI tasks
3. S5 rule review workflow remains optional before live YAML rewrites
