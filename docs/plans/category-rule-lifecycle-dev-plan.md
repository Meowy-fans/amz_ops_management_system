# Category Rule Lifecycle — Development Plan

> Epic: `EPIC-AMZ-LISTING-RULE-AUTHORING-V2` Phase 4
> ADR: `docs/decisions/ADR-2026-06-28-category-rule-lifecycle-scope.md`
> Updated: 2026-06-28

## 1. Goal

Deliver an **operator-runnable lifecycle** for maintaining usable per-category listing
attribute rules (`api_attribute_rules/*.yaml`), from first onboarding through audited
go-live and ongoing Amazon feedback updates.

**Not in this plan:** V2 LIVE cutover (`--engine v2 --no-dry-run`), content generation
fixes, Web UI.

## 2. Lifecycle Overview

```text
                    ┌─────────────────────────────────────────┐
                    │  Amazon VALIDATION_PREVIEW / LIVE PUT   │
                    └─────────────────────────────────────────┘
                                        ▲
┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌─────────────┐
│ S8       │   │ S9       │   │ S10          │   │ S11         │
│ Onboard  │──►│ Approve  │──►│ Promote      │──►│ Feedback    │
│ category │   │ rules    │   │ live_eligible│   │ triage      │
└──────────┘   └──────────┘   └──────────────┘   └─────────────┘
      ▲                ▲                ▲                │
      │                │                │                ▼
   S1-S3           pending_rule_    promote           learn/apply
   (existing)       review table     checklist         + S4 extend
                                                         │
                    ┌────────────────────────────────────┘
                    ▼
              S12 emit guard (engine + review scan)
```

## 3. Slice Schedule

Recommended implementation order (dependencies first):

| Order | Slice | Est. | Depends on | Deliverables |
| --- | --- | --- | --- | --- |
| 1 | **S9** | 3–5 d | S5 read-only | Migration, repository, `approve-rule`, YAML writeback |
| 2 | **S12** | 2–3 d | — | Enricher guard, compose strip, `risk_partial_emit` scan |
| 3 | **S10** | 2–3 d | S9, S7 | `promote-category-rules-v2`, checklist, backup + audit |
| 4 | **S8** | 3–4 d | S1–S3, S7 | `onboard-category-v2`, state manifest |
| 5 | **S11** | 4–5 d | S9, S4 | `analyze-listing-feedback-v2`, triage rules, optional apply |

**Total Phase 4: ~14–20 person-days** (after S0–S7 ~20–35 d already spent/in progress).

## 4. Slice Specifications

### S9 — Layer 1 review closure

**Modules**

| Module | Action |
| --- | --- |
| `rule_review_service_v2.py` | Add approve/writeback, blocking item taxonomy |
| `pending_rule_review_repository.py` | New |
| Alembic `011_amz_listing_pending_rule_review` | New |

**CLI**

```bash
# Existing (read-only)
python3 main.py --task review-pending-rules --category CHAIR

# New
python3 main.py --task approve-rule --category CHAIR \
  --path-key finish_type.value --decision safe_default \
  --reviewer operator@example --no-dry-run
```

**Decisions enum:** `safe_default` | `manual_review` | `omit_attribute` | `coverage_ignore` | `waived`

**Acceptance**

- [x] Approve writes YAML + audit row; re-run review shows item resolved
- [x] Idempotent re-approve updates `decided_at`, not duplicate rows
- [x] Unit tests: approve each decision type

---

### S12 — Runtime emit guard

**Modules**

| Module | Change |
| --- | --- |
| `optional_rule_children_enricher_v2.py` | Skip bootstrap for `coverage_ignore_required` roots |
| `listing_payload_engine_v2.py` | Post-compose strip incomplete ignore-listed attrs |
| `rule_review_service_v2.py` | `risk_partial_emit` when ignore root has `attributes` block |

**Acceptance**

- [x] BED_FRAME-style MSA: offline pass + Preview pass with omit (no 99022)
- [x] Unit: enricher does not inject `{marketplace_id}` for ignored roots
- [x] `review-pending-rules` flags CABINET-style correct config (ignore only, no block)

---

### S10 — Go-live promotion

**Modules**

| Module | Action |
| --- | --- |
| `category_rule_promotion_v2.py` | New — checklist evaluator |
| `rule_review_service_v2.py` | Expose blocking count for promote gate |

**CLI**

```bash
python3 main.py --task promote-category-rules-v2 --category CHAIR --no-dry-run
# Checks: review clear, s7 KPI file or inline thresholds, optional preview pass rate
# Writes: mode live_eligible, backup bed_frame.yaml.bak.TIMESTAMP, audit row
```

**Promote checklist (v1)**

| Check | Source |
| --- | --- |
| `review-pending-rules` blocking items = 0 | S9 |
| S7 offline: `zero_missing == sku_count` | acceptance JSON or re-run |
| S7 preview: `validation_preview_passed >= 1` (configurable) | optional flag |
| Golden regression | skip if category not in golden set |
| Current `mode == dry_run` | loader |

**Acceptance**

- [x] Promote fails closed when any check fails
- [x] Promote with `--no-dry-run` creates backup; submitter accepts LIVE for category
- [x] Re-promote idempotent when already `live_eligible`

---

### S8 — Onboarding orchestration

**Modules**

| Module | Action |
| --- | --- |
| `category_onboarding_v2.py` | New — pipeline runner |
| `config/.../category_rule_state/` optional | Per-category JSON state |

**CLI**

```bash
python3 main.py --task onboard-category-v2 --category BED_FRAME \
  --reference TABLE --sample-skus 4 --run-s7-offline
```

**Pipeline steps (default)**

1. Validate schema cached + ≥1 sample SKU
2. `generate-rule-skeleton-v2` (overwrite)
3. `reuse-rule-patterns-v2` (if `--reference`)
4. `map-rule-fields-v2` (pool SKUs)
5. Operator patches (documented hooks for GTIN omit pattern, dimension_strategy)
6. `review-pending-rules`
7. `s7_rule_authoring_acceptance.py` offline (+ optional `--preview`)

**Acceptance**

- [x] Single command produces dry_run yaml + acceptance report path
- [x] Fails early if no schema or no SKUs
- [x] State file records last run timestamp and KPI summary

---

### S11 — Feedback triage and rule updates

**Modules**

| Module | Action |
| --- | --- |
| `listing_feedback_analyzer_v2.py` | New — classify issues by code |
| `rule_feedback_adapter_v2.py` | Extend beyond 90220 suggestions |
| Reuse `FeedbackLearningAdapterV2` | Ingest step before analyze |

**CLI**

```bash
python3 main.py --task analyze-listing-feedback-v2 --category BED_FRAME --limit 50
python3 main.py --task learn-required-from-submissions --category BED_FRAME
python3 main.py --task learn-rules-from-feedback-v2 --category BED_FRAME --no-dry-run
```

**Triage routing (v1)**

| Code family | Route | Action |
| --- | --- | --- |
| 90220 | Rule (Layer 1) | learn → YAML placeholder → approve |
| 99022 partial value | Rule (Layer 1) | suggest omit / remove attribute block |
| 90244 enum | Rule or data | suggest enum source / normalizer |
| 100339 HTML/content | Layer 2 / content | **not** auto YAML rule change |
| WARNING | Log only | no auto patch |

**Acceptance**

- [x] Analyze report groups issues with suggested route
- [x] Learn + apply still requires S9 approve for non-placeholder patches
- [x] Test fixtures for 90220, 99022, 100339 classification

## 5. Testing Strategy

| Layer | Tests |
| --- | --- |
| S9 | Repository CRUD, approve writeback, YAML round-trip |
| S12 | Enricher + strip unit; BED_FRAME MSA regression |
| S10 | Checklist pass/fail matrix; backup file created |
| S8 | Integration test with mocked schema + 1 SKU |
| S11 | Issue classifier unit; end-to-end learn dry-run |

Run before each promote:

```bash
python3 scripts/s6_golden_regression.py
python3 scripts/s7_rule_authoring_acceptance.py --preview <CATEGORY>
```

## 6. Documentation Deliverables

| Doc | When |
| --- | --- |
| `docs/module-design/rule-review-service-v2.md` | S9 |
| `docs/module-design/category-rule-promotion-v2.md` | S10 |
| `docs/module-design/category-onboarding-v2.md` | S8 |
| `docs/module-design/listing-feedback-analyzer-v2.md` | S11 |
| Operator runbook section in Epic §9 | S8 ship |

## 7. Rollout

1. ~~**S12 + S9** to production first~~ ✅ Done (2026-06-28).
2. ~~**S10** for CHAIR/TABLE/BED_FRAME~~ ✅ All promoted `live_eligible`.
3. ~~**S8** documented as standard path~~ ✅ `docs/runbooks/category-onboarding-v2.md`.
4. **S11** enabled per-category — operational; use after S9 stable.

**Epic closed 2026-06-28.**

## 8. Task IDs (project TODO.md)

| ID | Slice | Title |
| --- | --- | --- |
| TASK-146 | S9 | Layer 1 rule review persistence + approve-rule CLI |
| TASK-147 | S12 | coverage_ignore emit guard + risk_partial_emit review |
| TASK-148 | S10 | promote-category-rules-v2 go-live gate |
| TASK-149 | S8 | onboard-category-v2 orchestration CLI |
| TASK-150 | S11 | analyze-listing-feedback-v2 triage + apply pipeline |

See `TODO.md` for status tracking.
