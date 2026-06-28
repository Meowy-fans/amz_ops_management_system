# 全量待发品发品验证 — Phase 2 批次报告

**日期**: 2026-06-28  
**镜像**: `2026-06-28-phase2-onboard-complete`  
**命令**: `patch_phase2_onboard_rules.py` → `promote-category-rules-v2` → `generate-listing-api --engine v2 --strict-validation --only-not-on-amazon`

## Phase 2 结果（dry_run 8 品类 / 8 SKU）— **DONE**

### 流程完成度

| 步骤 | 状态 |
| --- | --- |
| onboard skeleton | ✅ 8/8 |
| YAML 规则修补（`patch_phase2_onboard_rules.py`） | ✅ |
| Layer 1 review blocking 清零 | ✅ 8/8 |
| promote → `live_eligible` | ✅ **8/8** |
| 池 SKU 发品验证 | ✅ 见下表 |

### 逐品类终态

| 品类 | Pool SKU | mode | 发品验证终态 | 备注 |
| --- | --- | --- | --- | --- |
| PLANTER | meow251108CemWx | live_eligible | **PASS** | `validation_preview_passed` |
| SUITCASE | meow251108pbQsB | live_eligible | **PASS** | promote 门禁 preview passed；后续 strict 因 `amz_listing_log` GENERATED 不再生成 plan |
| ARTIFICIAL_TREE | meow251108LptML | live_eligible | **PASS** | |
| CLIMBING_PLANT_SUPPORT_STRUCTURE | meow251108LzHLh | live_eligible | **PASS** | |
| FURNITURE | meow251108cJXHN | live_eligible | **PASS** | |
| LADDER | meow251108eFqEd | live_eligible | **PASS** | 修 `special_feature` 超长（90225）后 promote |
| BICYCLE | meow251108ceBe7 | live_eligible | **PASS** | 补 `frame.material`、修 `size` 超长后 promote |
| DESK | meow2506084DCXZ | live_eligible | **SKIP-EXISTING** + **PASS-WARN** | 已在 Amazon；preview 仅 `100335` 尺寸 warning（out）；promote 未要求 preview |

### 关键修补

- 商业属性：`fulfillment_availability` / `condition_type` / `list_price` / `batteries_required` 对齐 `bed_frame.yaml`
- `coverage_ignore_required`: `merchant_suggested_asin`, `merchant_shipping_group`
- 类目特修：LADDER `special_feature`、BICYCLE `frame.material`+`size`、DESK `base.material`+`top.material`

### 工件

| 文件 | 用途 |
| --- | --- |
| `scripts/patch_phase2_onboard_rules.py` | Phase 2 YAML 批量修补 |
| `config/.../api_attribute_rules/{desk,...,planter}.yaml` | promoted 规则（`mode: live_eligible`） |
| `docs/test-reports/2026-06-28-*-onboard-acceptance.json` | S7 验收快照 |

## 结论

Phase 2 **已完成**：8 品类全部 `live_eligible`，7 个未上 Amazon 池 SKU 均达 `validation_preview_passed`（或 documented skip/warn）。Epic 内 in-scope blocker 已清零。
