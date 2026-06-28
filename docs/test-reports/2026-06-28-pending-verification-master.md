# 全量待发品发品验证 — 主台账

**启动日期**: 2026-06-28  
**池口径**: `pending-statistics` / 离线报表未命中  
**生产镜像**: `amz-listing-management-system:2026-06-28-phase2-onboard-complete`

## 总览

| 指标 | 值 |
| --- | --- |
| 待发 SKU 总数 | **120** |
| Phase 1 live_eligible | 7 品类 / 82 SKU — **DONE** |
| Phase 2 onboard | 8 品类 / 8 SKU — **DONE**（8/8 `live_eligible`） |
| Phase 3 UNMAPPED | 30 SKU — **DONE**（23 PASS / 7 warn out） |

## Phase 2 品类进度（8 SKU）

| 品类 | SKU | mode | 验证终态 |
| --- | --- | --- | --- |
| PLANTER | meow251108CemWx | live_eligible | **PASS** |
| SUITCASE | meow251108pbQsB | live_eligible | **PASS** |
| ARTIFICIAL_TREE | meow251108LptML | live_eligible | **PASS** |
| CLIMBING_PLANT_SUPPORT_STRUCTURE | meow251108LzHLh | live_eligible | **PASS** |
| FURNITURE | meow251108cJXHN | live_eligible | **PASS** |
| LADDER | meow251108eFqEd | live_eligible | **PASS** |
| BICYCLE | meow251108ceBe7 | live_eligible | **PASS** |
| DESK | meow2506084DCXZ | live_eligible | **SKIP-EXISTING**（`100335` warn out） |

## 执行日志（续）

| 时间 | 阶段 | 动作 | 结果 |
| --- | --- | --- | --- |
| 2026-06-28 | 2c | `patch_phase2_onboard_rules.py` + 类目特修 | 8 YAML ready |
| 2026-06-28 | 2d | promote 8 品类 → `live_eligible` | 8/8 |
| 2026-06-28 | 2e | 池 SKU strict-preview 复验 | 7 PASS + 1 SKIP |
| 2026-06-28 | — | 部署 `phase2-onboard-complete` | 4 容器 up |
| 2026-06-28 | 3a | 10 供应商品类人工映射 + schema cache | O-005 解除 |
| 2026-06-28 | 3b | onboard/promote MAKEUP_VANITY、RIDE_ON_TOY、OUTDOOR_LIVING、FIRE_PIT | 4/4 `live_eligible` |
| 2026-06-28 | 3c | Phase 3 池 30 SKU strict-preview | **23 PASS** + 7 warn（CABINET/O-004 + 1 PT 建议） |

详见 `phase2.md`、`phase3.md`、`issues.md`。
