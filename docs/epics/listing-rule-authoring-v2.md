# EPIC: Category Rule Lifecycle (Listing Rule Authoring V2)

> Epic ID: `EPIC-AMZ-LISTING-RULE-AUTHORING-V2`
> Status: **Completed** (closed 2026-06-28)
> Date: 2026-06-27 (Phase 4 scope: 2026-06-28)
> Owner: amz-listing-management-system
> Predecessors:
> - `EPIC-AMZ-LISTING-REQUIREMENT-PAYLOAD-V2` (S0-S14 tooling first-pass complete, engine stable)
> - `EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES` (Completed 2026-06-15)
> Scope extension ADR: `docs/decisions/ADR-2026-06-28-category-rule-lifecycle-scope.md`
> Dev plan: `docs/plans/category-rule-lifecycle-dev-plan.md`

## Epic Goal (revised 2026-06-28)

Maintain a **usable, auditable, per-category listing attribute rule set** end-to-end:

```text
Onboard → Review → Promote (live_eligible) → Operate → Amazon feedback → Update rules
```

Phase 1–3 focused on **generating** V2-ready YAML (S1–S7). Phase 4 completes the
**operator lifecycle** so new categories do not depend on ad-hoc scripts or manual
`mode:` edits.

## Current Progress

Updated: 2026-06-28. **Epic closed.**

### Phase 1–3 (Rule generation) — complete

- ✅ S0 ADR: `docs/decisions/ADR-2026-06-27-listing-rule-authoring-v2.md`
- ✅ S1 `rule_skeleton_generator_v2.py` + CLI `generate-rule-skeleton-v2`
- ✅ S1 `optional_rule_children_enricher_v2.py`
- ✅ S2 `rule_field_mapper_v2.py` + CLI `map-rule-fields-v2`
- ✅ S3 `rule_pattern_reuse_v2.py` + CLI `reuse-rule-patterns-v2`
- ✅ S4 `rule_feedback_adapter_v2.py` + CLI `learn-rules-from-feedback-v2`
- ✅ S5/S9 Layer 1 review: `review-pending-rules` + `approve-rule` + audit table
- ✅ S6 `rule_migration_v2.py` + CLI `migrate-rules-v2` / `evaluate-rules-v2-golden`; golden 4/4 PASS
- ✅ S7: CHAIR 18/18 offline, 14/18 preview; TABLE 4/4+4/4; BED_FRAME 4/4 offline + 3/4 preview

### Phase 4 (Lifecycle) — complete

- ✅ S9 Layer 1 review closure (`approve-rule`, `amz_listing_pending_rule_review`)
- ✅ S12 Emit guard (`coverage_ignore` + no partial bootstrap)
- ✅ S10 `promote-category-rules-v2` go-live gate
- ✅ S8 `onboard-category-v2` orchestration
- ✅ S11 `analyze-listing-feedback-v2` feedback triage

### Production closure (2026-06-28)

- Image: `amz-listing-management-system:2026-06-28-category-rule-lifecycle`
- Promoted to `live_eligible`: **BED_FRAME**, **TABLE**, **CHAIR**
- Operator runbook: `docs/runbooks/category-onboarding-v2.md`
- pytest write guard: `rule_yaml_write_guard.py`

Reports: `docs/test-reports/2026-06-27-*`, `docs/test-reports/2026-06-28-*-lifecycle-*`.

## 1. Background

(See prior sections — V2 engine consumes schema + YAML; this epic produces and
**operates** YAML rules.)

### 1.1 Lifecycle vs tool fragments

| Operator need | Phase 1–3 | Phase 4 |
| --- | --- | --- |
| Generate rules for new category | S1–S3 CLI (manual chain) | S8 orchestration |
| Review rule quality | S5 scan only | S9 approve + audit |
| Enable LIVE submit | Manual `mode: live_eligible` | S10 promote gate |
| Learn from Amazon errors | S4 (90220 only) | S11 triage + routes |
| Prevent partial emit bugs | — | S12 engine guard |

### 1.2 Three Review Layers (unchanged)

```text
Layer 1 — Rule review (this epic S5/S9/S11)
Layer 2 — Value review (existing V2 pending_review_v2)
Layer 3 — Submission review (existing V1 ReviewManager)
```

## 2. Slice Breakdown

### Phase 1–3 (complete / in progress)

| Slice | Title | Est. | Status |
| --- | --- | --- | --- |
| S0 | ADR + design doc | 1-2 d | ✅ |
| S1 | Schema-driven rule skeleton V2 | 3-5 d | ✅ |
| S2 | Giga field auto-mapping | 3-5 d | ✅ |
| S3 | Cross-category pattern reuse | 2-3 d | ✅ |
| S4 | Feedback → YAML rule adapter (90220) | 2-3 d | ✅ |
| S5 | Rule review workflow | 3-5 d | ✅ |
| S6 | Legacy migration + golden regression | 2-3 d | ✅ |
| S7 | Multi-category acceptance | 2-4 d | ✅ |

### Phase 4 — Category Rule Lifecycle (new)

| Slice | Title | Est. | Summary |
| --- | --- | --- | --- |
| S9 | Layer 1 review closure | 3-5 d | Complete S5: `amz_listing_pending_rule_review`, `approve-rule`, YAML writeback |
| S12 | Runtime emit guard | 2-3 d | Enricher/strip for `coverage_ignore_required`; `risk_partial_emit` review scan |
| S10 | Go-live promotion gate | 2-3 d | `promote-category-rules-v2`: checklist → `mode: live_eligible` + backup + audit |
| S8 | Category onboarding orchestration | 3-4 d | `onboard-category-v2`: S1–S3 + S7 in one CLI; state manifest |
| S11 | Feedback triage → rule updates | 4-5 d | `analyze-listing-feedback-v2`; route 90220/99022/content; extend S4 apply path |

**Phase 1–3 total:** ~20–35 person-days (spent).  
**Phase 4 total:** ~14–20 person-days (estimated).

### Slice Dependency Graph (full epic)

```text
S0
 │
 ├─► S1 ──► S2 ──► S3 ───────────────► S8 (onboard)
 │                      │
 ├─► S4 ──► S5 ──► S9 (approve) ──► S10 (promote)
 │         │              │
 └─► S6 ──► S7 ─────────┴──► S11 (feedback)
              │
 S12 (guard) ─┴─ parallel after S9 design frozen
```

## 3. Success Criteria

### Phase 1–3 (existing — update checkmarks from S7 runs)

- [x] CHAIR ≥1 `validation_preview_passed`; 18/18 offline zero missing
- [x] TABLE 4/4 offline zero missing; 4/4 preview passed
- [x] BED_FRAME skeleton + 4/4 offline; 3/4 preview
- [x] Golden 4/4 SOFA/CABINET/HOME_MIRROR/OTTOMAN
- [x] CHAIR leaf TODO placeholder rate <20% (0/40 leaves, production 2026-06-28)
- [x] `review-pending-rules` lists Layer 1 gaps with blocking count
- [x] `approve-rule` writes YAML + audit; re-scan clears approved items
- [x] `risk_partial_emit` detects ignore-listed root with attribute block (MSA pattern)
- [x] Enricher no longer bootstraps ignored roots; strip drops incomplete ignore payloads
- [x] `promote-category-rules-v2` fails closed without S7/review clearance
- [x] Re-promote idempotent when already `live_eligible`
- [x] `onboard-category-v2` produces dry_run yaml + acceptance report in one run
- [x] `analyze-listing-feedback-v2` routes 100339 to content, 90220 to rule layer
- [x] Operator runbook documents full lifecycle (`docs/runbooks/category-onboarding-v2.md`)

## 4. Module Plan

### Existing (Phase 1–3)

| Module | Responsibility |
| --- | --- |
| `rule_skeleton_generator_v2.py` | S1 skeleton |
| `rule_field_mapper_v2.py` | S2 mapping |
| `rule_pattern_reuse_v2.py` | S3 reuse |
| `rule_feedback_adapter_v2.py` | S4 90220 → YAML |
| `rule_review_service_v2.py` | S5/S9 review |
| `rule_migration_v2.py` | S6 migration |

### New (Phase 4)

| Module | Slice | Responsibility |
| --- | --- | --- |
| `pending_rule_review_repository.py` | S9 | Audit persistence |
| `category_rule_promotion_v2.py` | S10 | Promote checklist |
| `category_onboarding_v2.py` | S8 | Pipeline orchestration |
| `listing_feedback_analyzer_v2.py` | S11 | Issue triage |
| `optional_rule_children_enricher_v2.py` | S12 | Ignore-list guard (modify) |
| `listing_payload_engine_v2.py` | S12 | Post-compose strip (modify) |

### New persistence

| Table | Slice | Purpose |
| --- | --- | --- |
| `amz_listing_pending_rule_review` | S9 | Layer 1 audit log |
| `amz_listing_category_rule_promotions` (optional) | S10 | Promote events; or reuse pending_rule_review with `decision=promoted` |

### CLI tasks

| Task | Phase | Status |
| --- | --- | --- |
| `generate-rule-skeleton-v2` | 1–3 | ✅ |
| `map-rule-fields-v2` | 1–3 | ✅ |
| `reuse-rule-patterns-v2` | 1–3 | ✅ |
| `learn-rules-from-feedback-v2` | 1–3 | ✅ |
| `migrate-rules-v2` | 1–3 | ✅ |
| `review-pending-rules` | 1–3 | ✅ |
| `approve-rule` | 4 | ✅ |
| `promote-category-rules-v2` | 4 | ✅ |
| `onboard-category-v2` | 4 | ✅ |
| `analyze-listing-feedback-v2` | 4 | ✅ |

## 5. Integration Boundary (revised §7)

**In scope (Phase 4 addition):**

- Minimal engine changes in S12 only: emit/omit consistency for `coverage_ignore_required`
- Promote changes YAML `mode` field; submitter already enforces `live_eligible`

**Still out of scope:**

- `build_read_only_plan()` signature changes (unless S12 strip is internal only — preferred)
- Layer 2 / content pipeline / HTML strip
- V2 LIVE cutover (`LISTING-PAYLOAD-V2` S14)
- Auto-promote without human `promote-category-rules-v2`

**Regression:** S6 golden + S7 acceptance required before any `promote-category-rules-v2 --no-dry-run`.

## 6. Open Questions (Phase 4)

1. **Promote preview KPI:** require ≥1 passed or ≥N% of pool?  
   **Leaning:** configurable threshold; default ≥1 for dry_run pool.

2. **State manifest:** file under `config/.../category_rule_state/` vs DB?  
   **Leaning:** JSON file per category first; DB if multi-operator concurrency needed.

3. **S11 auto-apply:** patch YAML without approve for 90220 placeholders only?  
   **Leaning:** yes for placeholders; all other patches require S9 approve.

4. **CHAIR/TABLE promote timing:** promote after Phase 4 ship or earlier with manual mode?  
   **Leaning:** use S10 gate; no manual `live_eligible` edits for new categories after S10 ships.

## 7. Operator Runbook (target state)

```bash
# 1. Onboard new category
python3 main.py --task onboard-category-v2 --category BED_FRAME --reference TABLE

# 2. Review + approve rule decisions
python3 main.py --task review-pending-rules --category BED_FRAME
python3 main.py --task approve-rule --category BED_FRAME --path-key ... --decision ...

# 3. Preview acceptance
python3 scripts/s7_rule_authoring_acceptance.py --preview BED_FRAME

# 4. Promote to live-eligible (enables LIVE submit for this category)
python3 main.py --task promote-category-rules-v2 --category BED_FRAME --no-dry-run

# 5. Ongoing: Amazon feedback
python3 main.py --task analyze-listing-feedback-v2 --category BED_FRAME
python3 main.py --task learn-rules-from-feedback-v2 --category BED_FRAME --no-dry-run
python3 main.py --task approve-rule ...
```

## 8. References

- ADR (original): `docs/decisions/ADR-2026-06-27-listing-rule-authoring-v2.md`
- ADR (Phase 4): `docs/decisions/ADR-2026-06-28-category-rule-lifecycle-scope.md`
- Dev plan: `docs/plans/category-rule-lifecycle-dev-plan.md`
- Tasks: `TODO.md` TASK-146 – TASK-150
