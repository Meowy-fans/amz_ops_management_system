# S7 Multi-Category Acceptance — Listing Rule Authoring V2

- Date: 2026-06-27
- Epic: `EPIC-AMZ-LISTING-RULE-AUTHORING-V2`
- Runner: `scripts/s7_rule_authoring_acceptance.py`
- Environment: container `amz-listing-management-system` (DB + Amazon SP-API)

## Gate Results

| Gate | Criterion | Result |
| --- | --- | --- |
| CHAIR preview | ≥1 SKU `validation_preview_passed` | **PASS** — 14 / 18 |
| CHAIR offline | 18-SKU pool zero `missing_required` | **PASS** — 18 / 18 |
| CHAIR YAML | Leaf TODO placeholder rate < 20% | **PASS** — 0 / 40 (0%) |
| TABLE offline | ≥1 SKU not `missing_only` | **PASS** — 4 / 4 (`missing_and_review`) |
| BED_FRAME smoke | Schema skeleton generated | **PASS** — 23 attrs, 36 leaf placeholders |

**Overall S7 (rule-authoring scope): PASS**

## CHAIR (18-SKU dry-run pool)

### Offline V2 coverage

| Status | Count |
| --- | --- |
| `clean` | 15 |
| `pending_review` | 3 |
| `missing_only` | 0 |
| `missing_and_review` | 0 |

All 18 SKUs have **zero missing required paths** under current `chair.yaml`.

### Amazon `VALIDATION_PREVIEW`

| Status | Count |
| --- | --- |
| `validation_preview_passed` | **14** |
| `validation_preview_issues` | 4 |

**Passed SKUs:** `meow2511081Gqqd`, `meow2511084CO3e`, `meow2511086ZxM4`,
`meow25110886U7W`, `meow251108969R3`, `meow251108c3W1l`, `meow251108Fifdz`,
`meow251108fKlrr`, `meow251108HE6cX`, `meow251108QOPQp`, `meow251108U21qE`,
`meow251108yArXW`, `meow251108Ywgzd`, `meow251108ZNCVC`

### 4 SKUs with preview issues (not rule gaps)

Failures are **supplier/content/data quality**, not missing YAML rules:

| SKU | Amazon codes | Root cause |
| --- | --- | --- |
| `meow251108D55jW` | 100335, 100339 | Dimension height > schema max; HTML in description |
| `meow251108KmRAD` | 100339, 90244 | HTML in description; invalid `country_of_origin` (MALAYSIA) |
| `meow251108soUjl` | 100335 | Depth/width exceed schema max |
| `meow251108tgYzy` | 100339 | HTML in product description |

No unexplained 90220 missing-required on these SKUs after rule enricher.

## TABLE (4-SKU pool)

| Metric | Value |
| --- | --- |
| Pool size | 4 |
| `missing_only` | 0 |
| `missing_and_review` | 4 |
| `dimension_strategy` in YAML | **missing** |
| Leaf TODO placeholder rate | 25% (7 / 28) |

TABLE meets S7 **offline** gate (not `missing_only`) but rules remain immature —
V1-era flat YAML without nested `children`. Full TABLE preview not required by S7.

## BED_FRAME (4-SKU pool, smoke)

| Metric | Value |
| --- | --- |
| `bed_frame.yaml` | **does not exist** (empty rule set + universal preset only) |
| Skeleton dry-run | 23 attributes, 36 leaf placeholders |
| `dimension_strategy` recommended | none (schema check returned no match in generator) |
| Offline pool | 4 / 4 `missing_only` (expected without rules) |

BED_FRAME S7 scope is skeleton smoke only — **PASS**.

## Commands

```bash
# Offline only (all categories)
docker exec -w /app amz-listing-management-system \
  python3 scripts/s7_rule_authoring_acceptance.py CHAIR TABLE BED_FRAME

# Include Amazon preview (CHAIR 18 SKUs, ~3–4 min)
docker exec -w /app amz-listing-management-system \
  python3 scripts/s7_rule_authoring_acceptance.py --preview CHAIR
```

## Follow-ups (outside S7 rule-authoring scope)

1. **Content pipeline**: strip HTML from `product_description` before preview (100339)
2. **Dimension clamping**: post-processor or supplier normalization for schema max (100335)
3. **Country of origin**: map `MALAYSIA` → `MY` or fix Giga field (90244)
4. **TABLE**: run S1–S3 pipeline (`generate-rule-skeleton-v2` + mapping + reuse)
5. **Production**: rebuild image so `chair.yaml` + enricher ship together
