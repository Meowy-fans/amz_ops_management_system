# ADR-2026-06-28: Category Rule Lifecycle — Epic Scope Extension

**日期**: 2026-06-28
**状态**: Accepted
**修订**: `ADR-2026-06-27-listing-rule-authoring-v2.md`（Phase 4 扩展，非推翻）

## Context

Phase 1–3 of `EPIC-AMZ-LISTING-RULE-AUTHORING-V2` delivered S1–S7 tooling (skeleton,
field mapping, pattern reuse, feedback adapter, migration, multi-category acceptance).
Operational gaps remain:

1. **No orchestrated onboarding** — operators manually chain CLI steps for new categories.
2. **Layer 1 review incomplete** — `review-pending-rules` is read-only; `approve-rule`
   and `amz_listing_pending_rule_review` are not implemented.
3. **No auditable go-live path** — `mode: live_eligible` is edited by hand; no promote
   checklist tied to S7 / Preview KPIs.
4. **Narrow feedback loop** — S4 covers 90220 only; no structured triage for 99022
   (partial emit), enum/content issues, or rule-vs-content classification.
5. **Emit/omit inconsistency** — `coverage_ignore_required` blocks offline missing but
   `OptionalRuleChildrenEnricherV2` can still bootstrap partial attributes (MSA 99022).

The original ADR stated "no engine changes on the primary path." Phase 4 accepts
**minimal engine guard changes** required for lifecycle safety.

## Decision

Extend `EPIC-AMZ-LISTING-RULE-AUTHORING-V2` scope to **Category Rule Lifecycle**
covering the full operator workflow:

```text
Onboard (S8) → Review (S9) → Promote (S10) → Operate → Feedback (S11) → Guard (S12)
```

### S8 — Category onboarding orchestration

- New CLI `onboard-category-v2` chains S1–S3 (+ optional S7 offline gate).
- Optional state manifest (YAML or DB row) records pipeline stage and last acceptance run.

### S9 — Layer 1 review closure (complete S5)

- Alembic migration: `amz_listing_pending_rule_review`.
- CLI `approve-rule` writes decisions to audit table **and** patches authoritative YAML.
- Decisions: `safe_default`, `manual_review`, `omit_attribute`, `coverage_ignore`.

### S10 — Go-live promotion gate

- New CLI `promote-category-rules-v2` sets `mode: live_eligible` only when checklist passes.
- Checklist (minimum): S7 offline KPI, Preview KPI (if `--preview` run recorded),
  `review-pending-rules` no blocking items, golden regression (if category in golden set).
- Writes YAML backup before promote; records promote event in audit table.

### S11 — Amazon feedback triage → rule updates

- New CLI `analyze-listing-feedback-v2` classifies submission/listing issues by code family.
- Extends S4: 90220 → `learn-rules-from-feedback-v2`; 99022 partial emit → suggest
  omit/suppress; content/HTML (e.g. 100339) → route to Layer 2, not rule YAML.
- Optional `apply-rule-feedback-v2` applies approved patches after Layer 1 review.

### S12 — Runtime emit guard (minimal engine change)

- `OptionalRuleChildrenEnricherV2`: do **not** bootstrap attributes listed in
  `coverage_ignore_required`.
- Post-compose strip: drop attribute keys in ignore list when value is incomplete
  (missing required child `value`).
- `RuleReviewServiceV2`: new issue type `risk_partial_emit` when ignore-listed root
  still has an `attributes.*` block.

## Boundaries (unchanged / explicit out-of-scope)

| Still in scope | Still out of scope |
| --- | --- |
| YAML rules + Layer 1 CLI/audit | Layer 2 SKU value review (existing) |
| Promote to `live_eligible` | V2 engine full cutover / `--engine v2 --no-dry-run` LIVE |
| Minimal emit guard | Content pipeline (HTML strip, description generation) |
| Feedback triage for rule layer | Web UI for rule review |

## Consequences

**Positive**

- Operator workflow matches documented safety model (dry_run → review → promote).
- MSA-class regressions blocked by guard + review, not tribal YAML knowledge.
- Feedback loop closes beyond 90220 with explicit rule vs content routing.

**Negative**

- Epic estimate grows by ~15–25 person-days (S8–S12).
- S12 requires coordinated engine + YAML deploy (revised integration boundary).
- Promote gate must be maintained as KPIs evolve.

## References

- Epic: `docs/epics/listing-rule-authoring-v2.md` (Phase 4)
- Dev plan: `docs/plans/category-rule-lifecycle-dev-plan.md`
- Incident: `docs/test-reports/2026-06-27-bed-frame-rule-authoring-pipeline.md` (MSA 99022)
