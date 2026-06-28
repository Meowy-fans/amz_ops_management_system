# 全量待发品发品验证 — Phase 3 批次报告（UNMAPPED → 人工映射）

**日期**: 2026-06-28  
**池**: 30 SKU / 10 供应商品类（原 `inventory.json` UNMAPPED）  
**脚本**: `scripts/apply_phase3_manual_mappings.py`、`scripts/patch_phase2_onboard_rules.py`、`scripts/run_phase3_strict_preview.py`

## 结果摘要

| 指标 | 值 |
| --- | --- |
| 人工映射写入 | **10** 供应商品类 → Amazon PT |
| 新 onboard + promote | **4** 品类（MAKEUP_VANITY、RIDE_ON_TOY、OUTDOOR_LIVING、FIRE_PIT） |
| 复用已有 `live_eligible` | **4** 品类（CABINET、FURNITURE、TABLE、ARTIFICIAL_TREE） |
| strict-preview（30 SKU） | **23 PASS** / **7 issues**（0 blocked） |

**结论**：O-005 类目映射阻塞已解除；30 SKU 全部进入 V2 发品验证路径，无 `blocked_attribute_coverage` / `blocked_variation_resolution`。

## 人工映射表

| 供应商品类 | SKU | Amazon PT | 备注 |
| --- | ---: | --- | --- |
| 10019 Makeup Vanities | 12 | MAKEUP_VANITY | onboard + promote |
| 10031 TV Entertainment | 5 | CABINET | 已有 live_eligible |
| 10006 Kids ride-on | 4 | RIDE_ON_TOY | onboard + promote |
| 10051 Kitchen Islands | 2 | FURNITURE | 已有 live_eligible |
| 10145 Saunas | 2 | **OUTDOOR_LIVING** | SAUNA PT `4000003` 不支持；改映射后 onboard |
| 10107 Xmas set | 1 | ARTIFICIAL_TREE | 已有 live_eligible |
| 10149 Laundry counter | 1 | FURNITURE | 已有 live_eligible |
| 10159 Picnic table | 1 | TABLE | 已有 live_eligible |
| 10165 Fire pit | 1 | FIRE_PIT | onboard + promote |
| 10931 Storage cabinet | 1 | CABINET | 已有 live_eligible |

## 新品类 promote 结果

| 品类 | zero_missing | preview passed | mode |
| --- | --- | --- | --- |
| MAKEUP_VANITY | 15/15 | 14/15（promote gate） | **live_eligible** |
| RIDE_ON_TOY | 4/4 | 4/4 | **live_eligible** |
| OUTDOOR_LIVING | 2/2 | 2/2 | **live_eligible** |
| FIRE_PIT | 1/1 | 1/1 | **live_eligible** |

## strict-preview 逐类目（30 SKU 池）

| 品类 | SKU | PASS | issues | 典型 issue |
| --- | ---: | ---: | ---: | --- |
| MAKEUP_VANITY | 12 | 11 | 1 | `18367` PT 建议改 HOME_MIRROR（WARNING） |
| RIDE_ON_TOY | 4 | 4 | 0 | — |
| OUTDOOR_LIVING | 2 | 2 | 0 | — |
| FIRE_PIT | 1 | 1 | 0 | — |
| FURNITURE | 3 | 3 | 0 | — |
| TABLE | 1 | 1 | 0 | — |
| ARTIFICIAL_TREE | 1 | 1 | 0 | — |
| CABINET | 6 | 0 | 6 | `100335` 尺寸超上限（WARNING） |

明细 JSON：`2026-06-28-phase3-strict-preview.json`

## 规则修补要点

- `makeup_vanity.yaml`：`item_shape`、`included_components`、`number_of_items` safe_default
- `ride_on_toy.yaml`：`target_gender` → `unisex`，`manufacturer_minimum_age` → `36`（月）
- `outdoor_living.yaml`：patch 补齐 `contains_liquid_contents`、`power_source_type`、`required_product_compliance_certificate`；`merchant_suggested_asin` coverage_ignore
- `patch_phase2_onboard_rules.py`：新增 `OUTDOOR_LIVING`、RIDE_ON_TOY 特修

## Out-of-scope 残留（验证完成，非引擎 blocker）

| ID | 范围 | 说明 |
| --- | --- | --- |
| O-004 | CABINET 6 SKU | `100335` 超大尺寸 WARNING |
| O-005 | — | **CLOSED**（人工映射完成） |
| — | MAKEUP_VANITY `meow2506285RSQ7` | `18367` Amazon PT 重分类建议（WARNING） |

## 状态

**Phase 3 DONE** — 30 SKU 发品验证路径已打通；7 个 issues 均为 Amazon WARNING，记 out-of-scope。
