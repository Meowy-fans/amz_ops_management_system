# 待发品验证 — 问题登记表

**Scope**: Epic `EPIC-AMZ-LISTING-REQUIREMENT-PAYLOAD-V2` + Rule Authoring V2  
**更新**: 2026-06-28（Phase 1–3 续跑完成）

## In-scope（引擎 / 规则层，必须修或明确 review 闭环）

| ID | 品类 | SKU/实体 | 现象 | 根因 | 方案 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| I-001 | CHAIR | variation parent | `4000001` depth 嵌套数组 | `OptionalRuleChildrenEnricherV2` 误包 measure | `2026-06-28-chair-parent-dims-fix` | **FIXED** |
| I-002 | CHAIR | 86U7W, c3W1l, KmRAD | `needs_review` `included_components` | LLM 先于 `safe_default: Chair` | `chair.yaml` safe_default 移至 LLM 前 | **FIXED** `2026-06-28-pending-verification-batch` |
| I-003 | TABLE | 4 SKU | `blocked_attribute_coverage` `frame` | Required `frame` 无 schema 子节点 | `EvidenceResolverV2` YAML-only children | **FIXED** `2026-06-28-table-frame-resolver-fix` |

## Out-of-scope（验证完成但需其他 Epic / 业务处理）

| ID | 品类 | SKU | 现象 | 层 | 方案归属 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| O-001 | CHAIR | D55jW, tgYzy, KmRAD | `100339` HTML in description | Content | 清洗 product_description | OPEN |
| O-002 | CHAIR | soUjl, D55jW | `100335` 尺寸超上限 | 业务/合规 | 选品剔除或接受 warning | OPEN |
| O-003 | HOME_MIRROR | 部分 | `blocked_variation_resolution` Color uniqueness | 变体业务 | 人工变体策略 | OPEN |
| O-004 | CABINET | 部分 | `100335` width>42in | 业务/quality gate | TASK-134 类 | OPEN |
| O-005 | UNMAPPED | 30 SKU | `auto-discover` 全部 `Written: False` | 类目映射 | 人工映射（`apply_phase3_manual_mappings.py`） | **CLOSED** |
| O-006 | TABLE | FAsJo, PlHb2 | `blocked_variation_resolution` | 变体业务 | 变体 theme/属性区分策略 | OPEN |

## 本轮批次结果

### Phase 1（live_eligible 7 品类 / 82 SKU）— 见 phase1 报告 + 修后复跑

| 品类 | 结果摘要 | Scope |
| --- | --- | --- |
| OTTOMAN | 2/2 `skipped_existing` | 验证完成 |
| BED_FRAME | 3 passed, 1 issues (`100339`) | out |
| TABLE | 2 passed, 2 variation block（修 I-003 后） | out O-006 |
| CABINET | 11 skipped, 4 issues (`100335`) | out |
| HOME_MIRROR | 16 skipped, 5 variation block | out O-003 |
| SOFA | 16 skipped, 1 passed, 2 issues (`100335`) | out |
| CHAIR | **15 passed**, 4 issues, parent passed | out O-001/O-002；I-002 **FIXED** |

### Phase 2（dry_run 8 品类）

| 品类 | 结果 | Scope |
| --- | --- | --- |
| 8× onboard | skeleton completed | in：规则迭代待续 |
| 7× strict-preview | `blocked_attribute_coverage` | in：补规则 |
| DESK | `skipped_existing_scope` | 移出池 |

### Phase 3（UNMAPPED 30 SKU）— **DONE**

| 品类 | strict-preview | Scope |
| --- | --- | --- |
| MAKEUP_VANITY ×12 | 11 PASS, 1 warn (`18367` PT 建议) | out |
| RIDE_ON_TOY ×4 | 4 PASS | 验证完成 |
| OUTDOOR_LIVING ×2 | 2 PASS | 验证完成 |
| FIRE_PIT ×1 | 1 PASS | 验证完成 |
| FURNITURE ×3 | 3 PASS | 验证完成 |
| TABLE ×1 | 1 PASS | 验证完成 |
| ARTIFICIAL_TREE ×1 | 1 PASS | 验证完成 |
| CABINET ×6 | 6 issues (`100335`) | out O-004 |

O-005 人工映射已闭环。报告：`phase3.md`、`2026-06-28-phase3-strict-preview.json`

详见 `phase1.md` / `phase2.md` / `phase3.md`。
