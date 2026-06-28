# Live Categories — V2 Rule Regeneration (side-by-side drafts)

**Date**: 2026-06-28  
**Script**: `scripts/regenerate_live_category_rules_v2.py`

## Purpose

Backup current `live_eligible` YAMLs and generate **V2 onboarded drafts** in a separate
directory for unified acceptance and iteration — **without changing production rules**.

## Artifacts

| Artifact | Path |
| --- | --- |
| Live backups | `config/.../api_attribute_rules/backups/live_eligible_2026-06-28/*.yaml` |
| V2 drafts (`mode: dry_run`) | `config/.../api_attribute_rules/v2_onboarded/*.yaml` |
| Regeneration summary (JSON) | `docs/test-reports/2026-06-28-live-categories-v2-regenerate.json` |
| Draft vs live offline KPIs | `docs/test-reports/2026-06-28-live-categories-v2-draft-acceptance.json` |
| Per-category onboard acceptance | `docs/test-reports/2026-06-28-{category}-onboard-acceptance.json` |
| Onboard state | `config/.../category_rule_state/{category}.json` |

## Pipeline per category

`onboard-category-v2`: skeleton → reuse (reference) → map → review → S7 offline

| Category | Reference | Legacy attrs | Draft attrs | Layer 1 blocking (draft) |
| --- | --- | --- | --- | --- |
| CABINET | TABLE | 13 | 27 | 14 |
| HOME_MIRROR | CABINET | 10 | 21 | 12 |
| SOFA | TABLE | 13 | 22 | 14 |
| OTTOMAN | SOFA | 13 | 25 | 14 |

Operator root keys (`dimension_strategy`, `coverage_ignore_required`, `post_processors`, etc.)
were **copied from live backup** onto each draft after onboard.

## Offline acceptance (canonical live vs v2 draft)

| Category | Live `zero_missing` / pool | Draft `zero_missing` / pool |
| --- | --- | --- |
| CABINET | **1/1** | 0/1 |
| HOME_MIRROR | **5/5** | 0/5 |
| SOFA | **19/19** | 0/19 |
| OTTOMAN | **2/2** | 0/2 |

Live rules remain production-grade. Drafts expand schema coverage (more attributes / children)
and require Layer 1 review + approve before any promote.

## Production safety

Canonical files **unchanged**:

```
cabinet.yaml / home_mirror.yaml / sofa.yaml / ottoman.yaml  →  mode: live_eligible
```

## Next steps (operator)

1. Review drafts: `python3 main.py --task review-pending-rules --category <CAT>` (load from `v2_onboarded` via custom loader or temporarily swap paths)
2. Approve / patch blocking items
3. Re-run S7 offline + preview on drafts
4. When draft KPIs meet bar: promote draft to replace live (`promote-category-rules-v2 --no-dry-run`)

**Do not promote** until draft offline/preview matches or exceeds live baseline.
