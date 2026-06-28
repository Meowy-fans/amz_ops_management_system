# 全量待发品发品验证 — Phase 1 批次报告

**日期**: 2026-06-28  
**镜像**: `2026-06-28-chair-parent-dims-fix`  
**命令**: `generate-listing-api --engine v2 --strict-validation --only-not-on-amazon`

## Phase 1 结果（live_eligible 7 品类 / 82 SKU）

| 品类 | SKU | passed | issues | review | skipped | blocked | 备注 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| OTTOMAN | 2 | 0 | 0 | 0 | **2** | 0 | 已在 Amazon |
| BED_FRAME | 4 | **3** | 1 | 0 | 0 | 0 | FetOX `100339` HTML（out） |
| TABLE | 4 | 0 | 0 | 0 | 0 | **4** | 全部 `frame` LOW_CONFIDENCE（**in**） |
| CABINET | 14 | 0 | **4** | 0 | **11** | 0 | parent+child `100335` width（out） |
| HOME_MIRROR | 21 | 0 | 0 | 0 | **16** | **5** | 变体 resolution（out） |
| SOFA | 19 | **1** | **2** | 0 | **16** | 0 | dims `100335`（out） |
| CHAIR | 18 | **14** | **4** | **1** | 0 | 0 | parent **passed**；c3W1l review（in） |

### CHAIR 本轮亮点

- Variation parent `PARENT-672D5AC95F30` → **`validation_preview_passed`**
- `86U7W` 本轮 passed（LLM 非确定性，I-002 仍开放）
- In-scope 剩余：`c3W1l` `needs_review`（`included_components`）

### TABLE 本轮 blocker（in-scope）

全部 4 SKU：`LOW_CONFIDENCE_REQUIRED_ATTRIBUTE` @ **`frame`**  
→ strict path fail-closed，未达 Amazon preview  
→ 变体族 2 child 连带 `blocked_variation_resolution`（parent coverage 未过）

**方案**：补 `table.yaml` `frame` 高置信 source / enum，或 Layer-1 approve；与 I-003 对齐。

## 尚未开始

| 阶段 | 内容 | SKU |
| --- | --- | ---: |
| Phase 2 | dry_run 品类 onboard + 验证 | 8 |
| Phase 3 | UNMAPPED `auto-discover-category` | 30 |

## 工件

| 文件 | 用途 |
| --- | --- |
| `2026-06-28-pending-verification-inventory.json` | 120 SKU 快照 |
| `2026-06-28-pending-verification-master.md` | 主台账 |
| `2026-06-28-pending-verification-issues.md` | in/out scope 问题表 |
| `scripts/export_pending_verification_inventory.py` | 导出库存 |
| `scripts/collect_verification_ledger.py` | 从 audit 表汇总（注意历史行干扰） |

## 修后复跑（2026-06-28 晚）

**镜像**: `2026-06-28-pending-verification-batch`

| 修复 | 复跑结果 |
| --- | --- |
| I-003 TABLE frame resolver | 2/4 `validation_preview_passed`；2 `blocked_variation_resolution`（O-006） |
| I-002 CHAIR included_components | **15/18 passed**；0 `needs_review`；4 `validation_preview_issues`（O-001/O-002） |
| CHAIR parent I-001 | parent **passed** |

