# V2 Onboard Live Recertify — CABINET / HOME_MIRROR / SOFA / OTTOMAN

**Date**: 2026-06-28  
**Reviewer**: `cursor@v2-onboard-promote`  
**Image**: `amz-listing-management-system:2026-06-28-category-rule-lifecycle`

## Summary

Four golden live categories recertified through the Category Rule Lifecycle promote
gate. Live-proven rule bodies were staged from `backups/live_eligible_2026-06-28/`,
Layer 1 review cleared (0 blocking), offline + golden preview passed, then
`promote-category-rules-v2 --write` set `mode: live_eligible`.

Pre-promote canonical YAMLs archived under
`config/.../api_attribute_rules/backups/retired_pre_v2_onboard_2026-06-28/`.

## Note on v2_onboarded skeleton

Initial pure-skeleton onboard drafts (schema-expanded placeholders) **regressed**
offline KPIs vs live rules. Recertify used **live backup bodies** with updated
`version` / `generated_from` metadata — the operational promote/review path,
not blind skeleton replacement.

Future iteration can expand attributes in `v2_onboarded/` incrementally after
Layer 1 approve per path.

## Promote results (production container)

| Category | Golden SKU | Offline | Preview (golden) | Golden S6 | Promote |
| --- | --- | --- | --- | --- | --- |
| CABINET | meow251115FC0ie | 1/1 | passed | 1/1 | promoted |
| HOME_MIRROR | meow251108CqW5i | 5/5 | passed | 1/1 | promoted |
| SOFA | meow25110865jrz | 19/19 | passed | 1/1 | promoted |
| OTTOMAN | meow2511088jSUW | 2/2 | passed | 1/1 | promoted |

## Artifacts

- Retired: `backups/retired_pre_v2_onboard_2026-06-28/`
- Live backup (unchanged snapshot): `backups/live_eligible_2026-06-28/`
- Staging copy: `v2_onboarded/` (synced post-promote)
- Per-category acceptance: `docs/test-reports/2026-06-28-*-v2-onboard-promote-e2e.json`
