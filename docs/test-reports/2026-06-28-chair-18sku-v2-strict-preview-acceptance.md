# CHAIR 18 SKU V2 Strict-Preview Acceptance — 2026-06-28

**Image**: `amz-listing-management-system:2026-06-28-category-rule-lifecycle`  
**Command**:

```bash
python main.py --task generate-listing-api --category CHAIR \
  --sku <18 not-on-amazon SKUs> \
  --strict-validation --only-not-on-amazon --engine v2
```

**Scope**: 18 `live_eligible` CHAIR SKUs confirmed not on Amazon (cache miss pool).

## Executive Summary

| Metric | Result |
| --- | --- |
| V2 coverage block (`blocked_attribute_coverage`) | **0 / 18** ✅ |
| Reached Amazon VALIDATION_PREVIEW | **16 / 18** (12 singles + 4 variation-family rows) |
| `validation_preview_passed` (0 Amazon issues) | **12 / 18** (66.7%) |
| `validation_preview_issues` | **3 child + 1 parent** |
| `needs_review` (pre-preview) | **3 / 18** |

**Verdict**: Category Rule Lifecycle promote **有效** — 相对 promote 前（18/18 coverage block），V2 规则层已打通。剩余失败 **无 V2 引擎回归**；分为 review 流程（3）、内容/HTML（3）、尺寸超规（2）、parent 维度 shape（1）。

## Per-SKU Results (this batch, audit ids ≥ 122527)

| Status | SKU |
| --- | --- |
| **validation_preview_passed** | `1Gqqd`, `4CO3e`, `6ZxM4`, `969R3`, `Fifdz`, `fKlrr`, `HE6cX`, `QOPQp`, `U21qE`, `yArXW`, `Ywgzd`, `ZNCVC` |
| **validation_preview_issues** | `soUjl` (dims), `D55jW` (dims + HTML), `tgYzy` (HTML) |
| **needs_review** (no preview this run) | `86U7W`, `c3W1l`, `KmRAD` |
| **Parent** | `PARENT-08E9DEF253B2` — `validation_preview_issues` (dimension unit shape) |

Variation layout: **12 singles + 1 family (6 SKUs)**; family parent + `tgYzy` child submitted in this batch.

## Root Cause Analysis

### A. Epic 内 — Review 流程（3 SKU）

| SKU | Code | Path | Root cause |
| --- | --- | --- | --- |
| `86U7W`, `c3W1l`, `KmRAD` | `NEEDS_REVIEW_REQUIRED_ATTRIBUTE` | `included_components.value` | `chair.yaml` runs **LLM before** `safe_default: Chair`; CHAIR has `review_policy` enabled → LLM-sourced required path → `needs_review` |

**Fix path** (rule layer, not hardcode): reorder sources (default before LLM), or `--approve-human` on pending rows, or tighten LLM hint to return null when uncertain.

**Note**: `86U7W` / `c3W1l` have earlier same-day `validation_preview_passed` rows when LLM likely missed and default applied; this batch hit LLM values → review-only block. Non-deterministic LLM ordering explains promote S7 **14/18** vs this run **12/18**.

### B. Epic 外 / Content 层 — HTML in `product_description`（3 SKU）

| SKU | Amazon code | Evidence |
| --- | --- | --- |
| `D55jW`, `tgYzy`, `KmRAD` | `100339` ERROR | `content.description` contains Giga HTML (`<div>`, `<img>`, `<b>`); `text_join` passes through verbatim |

**Layer**: Content sanitization / listing content pipeline (Epic non-goal per lifecycle runbook §6). Not a V2 coverage bug.

**Fix path**: strip HTML before payload compose, or regenerate plain-text descriptions in content layer.

### C. Epic 外 — 物理尺寸超 Amazon 上限（2 SKU）

| SKU | Amazon code | Issue |
| --- | --- | --- |
| `soUjl` | `100335` WARNING | width 34.5 > 32.5 in; depth 39 > 35.04 in |
| `D55jW` | `100335` WARNING | height 41 > 40 in |

**Layer**: Product / business compliance (same class as CABINET TASK-134).

### D. Epic 内 — Parent 维度 payload shape（1 parent）

| Entity | Amazon code | Root cause |
| --- | --- | --- |
| `PARENT-08E9DEF253B2` | `4000001` ERROR | `item_depth_width_height.depth/width/height` rendered as **nested measure arrays** (`[{"unit","value"}]`) instead of flat `{"unit","value"}` on parent |

Example payload fragment:

```json
{"depth": [{"unit": "inches", "value": 19.0}], "width": [{"unit": "inches", "value": 22.6}], ...}
```

**Layer**: V2 `PayloadComposerV2` / CHAIR `item_depth_width_height` measure handling on variation parent (similar to prior OTTOMAN `measure_array` fix class).

## Epic 内 vs Epic 外 Tally

| Bucket | Count | Blocking V2 acceptance? |
| --- | --- | --- |
| Epic 内 — review (`included_components`) | 3 | Expected fail-closed; fix via approve / YAML source order |
| Epic 内 — parent dimension shape | 1 parent | Yes — V2 payload fix |
| Epic 外 — HTML `100339` | 3 | Content pipeline |
| Epic 外 — dimension `100335` | 2 | Product selection |
| **Clean pass** | **12** | ✅ V2 strict-preview evidence |

## Comparison to Promote-Time S7

| KPI | S7 (promote) | This batch |
| --- | --- | --- |
| Offline zero missing | 18/18 | 18/18 (no coverage block) |
| Preview passed | 14/18 | 12/18 |
| Delta | — | −2 (LLM review non-determinism on `included_components`; HTML/dims unchanged) |

## Recommended Next Steps

1. **V2 payload**: fix CHAIR variation-parent `item_depth_width_height` measure nesting (`4000001`).
2. **Rule YAML**: `included_components` — put `safe_default: Chair` before LLM, or batch `--approve-human` for 3 pending rows.
3. **Content**: sanitize `product_description` HTML for `D55jW` / `tgYzy` / `KmRAD` (content layer).
4. **Pool hygiene**: exclude oversize-chair SKUs (`soUjl`, `D55jW`) from canary pass-rate KPI or accept as business warnings only.

## Regression

No `blocked_attribute_coverage` across 18 SKUs. Golden compare gate (`evaluate-listing-v2-validation-compare`) unchanged **go 3/3** on CABINET/HOME_MIRROR/OTTOMAN (run same day).
