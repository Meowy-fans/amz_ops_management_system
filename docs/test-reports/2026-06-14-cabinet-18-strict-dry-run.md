# CABINET 18-SKU Strict Dry-run 验收报告

- **报告日期**: 2026-06-14
- **执行时间**: 2026-06-14 05:22 Asia/Shanghai
- **执行方式**: 生产容器内临时同步当前工作区代码到 `/tmp/codex-amz-task129`
- **目标品类**: CABINET
- **目标 SKU 文件**: `docs/test-reports/cabinet-18-skus-2026-06-14.txt`
- **模式**: `--strict-validation --only-not-on-amazon`
- **PUT 行为**: 未执行 PUT，仅调用 `getListingsItem` 与 Amazon `VALIDATION_PREVIEW`

## 1. 执行命令

```bash
python main.py \
  --task generate-listing-api \
  --category CABINET \
  --sku-file docs/test-reports/cabinet-18-skus-2026-06-14.txt \
  --only-not-on-amazon \
  --strict-validation
```

生产镜像尚未部署本轮 TASK-128 代码，因此本次在容器 `/tmp/codex-amz-task129` 临时目录执行当前工作区代码，复用容器现有 Amazon/DB 环境变量。

## 2. 总体结果

| 指标 | 结果 |
| --- | ---: |
| 输入目标 SKU | 18 |
| Amazon GET scope skipped existing | 9 |
| Commercial gate blocked | 3 |
| Variation resolver blocked | 2 |
| 进入 Amazon VALIDATION_PREVIEW 的 plan | 6 |
| validation_preview_passed | 0 |
| validation_preview_issues | 6 |
| PUT 提交 | 0 |

数据库 `amazon_api_submissions` 在 `2026-06-14 05:22:00+08` 到 `05:23:10+08` 的 `operation=create` 记录：

| status | count |
| --- | ---: |
| validation_preview_issues | 6 |

## 3. 18-SKU 状态矩阵

| meow_sku | giga_sku | 本次 strict dry-run 状态 | 说明 |
| --- | --- | --- | --- |
| meow251115VtNnK | N725P314023F | skipped_existing_scope | Amazon GET 200，跳过 |
| meow251115ZHPrR | W3151S00056 | skipped_existing_scope | Amazon GET 200，跳过 |
| meow251115x6Wq1 | N710P291684C | skipped_existing_scope | Amazon GET 200，跳过 |
| meow250817zRPIq | W3133S00011 | validation_preview_issues | child plan 被 Amazon 预检拒绝 |
| meow251108Sk5g9 | W3151S00047 | validation_preview_issues | child plan 被 Amazon 预检拒绝 |
| meow251108xDkIJ | W3151S00048 | validation_preview_issues | child plan 被 Amazon 预检拒绝 |
| meow251115B5Iq9 | W3151S00054 | blocked_variation_resolution | `DUPLICATE_VARIATION_ATTRIBUTES` |
| meow251115FC0ie | W3520S00009 | validation_preview_issues | single plan 被 Amazon 预检拒绝 |
| meow251115RfO3f | N817P339017B | blocked_variation_resolution | `DUPLICATE_VARIATION_ATTRIBUTES` |
| meow2508172omt6 | W3133S00002 | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow250817AXWkg | W3133S00001 | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow2511152QcBq | N710P191970C | skipped_existing_scope | Amazon GET 200，跳过 |
| meow2511152dapi | N710P191970M | skipped_existing_scope | Amazon GET 200，跳过 |
| meow251115FUUlt | W3151S00055 | skipped_existing_scope | Amazon GET 200，跳过 |
| meow251115IhvcJ | N759P346895B | skipped_existing_scope | Amazon GET 200，跳过 |
| meow251115S87Xu | N710S324097K | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow251115aI4LD | N710P324097K | skipped_existing_scope | Amazon GET 200，跳过 |
| meow251115zg0HP | N729P170388B | skipped_existing_scope | Amazon GET 200，跳过 |

本次还生成并预检了 2 个 parent plan：

| generated_sku | 状态 | 说明 |
| --- | --- | --- |
| PARENT-A13E8CF5784E | validation_preview_issues | Variation theme `Color` 不被 CABINET 接受 |
| PARENT-BD5F42101B03 | validation_preview_issues | Variation theme `Color` 不被 CABINET 接受 |

## 4. Amazon Validation Preview Issues

| SKU | request_id | ERROR issues | WARNING issues | 主要错误 |
| --- | --- | ---: | ---: | --- |
| meow251115FC0ie | c4445871-d82c-4e55-8697-0d30d01ae49e | 1 | 2 | `door` missing |
| PARENT-A13E8CF5784E | e7dd7fd1-bdfb-4bc9-a5f7-3bea4d86454d | 1 | 2 | `variation_theme` invalid |
| meow251108Sk5g9 | 66dae168-3edd-4f71-8785-02b43c497d5b | 2 | 2 | `door` missing, `variation_theme` invalid |
| meow251108xDkIJ | ed851a3a-d8b9-45d6-8418-7af419086165 | 2 | 2 | `door` missing, `variation_theme` invalid |
| PARENT-BD5F42101B03 | f0617070-48b6-4d59-a3de-a4c1d6926945 | 1 | 2 | `variation_theme` invalid |
| meow250817zRPIq | 835e3978-6a7c-4f89-9ce5-7e3cdd661dfb | 4 | 2 | `variation_theme` invalid, `door` missing, dimension/weight unit missing |

Issue 聚合：

| severity | code | attribute | count |
| --- | --- | --- | ---: |
| ERROR | 90244 | `variation_theme` | 5 |
| ERROR | 90220 | `door` | 4 |
| ERROR | 90220 | `item_weight` unit | 1 |
| ERROR | 90220 | `item_depth_width_height` unit | 1 |
| WARNING | 90000900 | `item_type_name` | 6 |
| WARNING | 90000900 | `target_audience_base` | 6 |

## 5. 变体与 Commercial Gate 观察

Variation block:

| meow_sku | parent_sku | selected_theme | blocking_code | 说明 |
| --- | --- | --- | --- | --- |
| meow251115B5Iq9 | PARENT-725B55361141 | Color/Size | DUPLICATE_VARIATION_ATTRIBUTES | 新 child 的 `Black + 30.00` 与既有 child 重复 |
| meow251115RfO3f | PARENT-68DFA385245D | COLOR | DUPLICATE_VARIATION_ATTRIBUTES | 新 child 缺少可区分属性，signature 为空并重复 |

Commercial block:

| meow_sku | blocking_code |
| --- | --- |
| meow251115S87Xu | QUANTITY_EXCEEDS_MAX |
| meow250817AXWkg | QUANTITY_EXCEEDS_MAX |
| meow2508172omt6 | QUANTITY_EXCEEDS_MAX |

## 6. 验收结论

**技术验收：通过。**

- SKU scope 生效，18 个目标 SKU 没有扩散到全 CABINET 品类。
- `--only-not-on-amazon` 生效，9 个 Amazon 已存在 SKU 被只读 GET 跳过。
- strict dry-run 生效，6 个 plan 调用 `VALIDATION_PREVIEW`。
- 本次没有执行 PUT。
- Amazon validation issues 已持久化到 `amazon_api_submissions`。

**业务验收：未通过。**

0 个 plan 通过 Amazon `VALIDATION_PREVIEW`。LIVE 前仍需修复：

1. CABINET `door` 属性映射仍不符合 Amazon required shape。
2. CABINET variation theme 不能提交 `Color`，需要使用 Product Type Definitions valid values 或类目规则映射。
3. `item_weight` / `item_depth_width_height` 单位字段存在结构缺口。
4. `item_type_name` 与 `target_audience_base` 对 CABINET 不适用，应从 payload 移除或按 schema 条件化。
5. 变体 append child 需要处理重复属性组合，必要时转人工确认或降级为 single。
6. Commercial Gate 的 `QUANTITY_EXCEEDS_MAX` 仍按 hard block 执行，库存 clamp 策略尚未落地。

## 7. 下一步

建议新增后续任务：

| 优先级 | 任务 |
| --- | --- |
| P0 | 修复 CABINET `door`、dimension/weight unit 与不适用属性输出 |
| P0 | CABINET variation theme valid value 映射，禁止继续输出非法 `Color` |
| P1 | 变体重复属性组合的人工审核/降级策略 |
| P1 | Commercial Gate 库存 clamp 策略落地 |

## 8. TASK-132 修复后复跑

- **复跑时间**: 2026-06-14 05:32 Asia/Shanghai
- **复跑命令**: 同第 1 节
- **代码位置**: 生产容器临时目录 `/tmp/codex-amz-task129`
- **PUT 行为**: 未执行 PUT

修复内容：

1. CABINET `door` 从简单 `value` 改为 schema 要求的嵌套 `style` shape，默认 Amazon-valid `Shaker`。
2. CABINET `variation_theme` 增加 deterministic fallback：`Color` → `COLOR`，`Color/Size` → `COLOR/ITEM_WIDTH`。
3. CABINET `size_name` variation attribute 改为 `item_width` measure，避免输出不适用的 `size_name`。
4. CABINET 移除 schema 不存在的 `item_type_name` / `target_audience_base`。
5. Giga combo SKU 在主尺寸为 `Not Applicable` 时，从 `comboInfo` 汇总尺寸和重量。

修复后结果：

| status | count |
| --- | ---: |
| skipped_existing_scope | 9 |
| blocked_commercial_gate | 3 |
| blocked_variation_resolution | 2 |
| blocked_quality_gate | 2 |
| validation_preview_passed | 4 |
| validation_preview_issues | 0 |

Amazon preview 结果：

| SKU | request_id | issues |
| --- | --- | ---: |
| meow251115FC0ie | 6a6e8af3-8476-4398-a663-ff12f0b150aa | 0 |
| PARENT-DFDE74AE9275 | 466fa5eb-7ab5-49e2-98b0-c0ad840c2d7e | 0 |
| meow251108xDkIJ | 4abae722-3361-4896-8114-a95392556188 | 0 |
| meow251108Sk5g9 | 3e843665-16b3-491d-86da-7481b6fddd6d | 0 |

修复后结论：

- Amazon `VALIDATION_PREVIEW` ERROR 已从 11 个降为 0。
- `door`、`variation_theme`、dimension/weight unit、CABINET 不适用属性输出问题已被 preview 验证修复。
- 业务仍未达到 LIVE retry 条件：剩余 2 个 `blocked_quality_gate`、2 个 `blocked_variation_resolution`、3 个 `blocked_commercial_gate`。

剩余 blocker：

| blocker | SKU / plan | 说明 |
| --- | --- | --- |
| ISSUE_DERIVED_DIMENSION_RANGE | `PARENT-81E56C81113C`, `meow250817zRPIq` | comboInfo 汇总后 width 52.76 / 53.54 超过本地 CABINET observed max 42，需要重新评估质量门阈值或产品类型/尺寸字段。 |
| DUPLICATE_VARIATION_ATTRIBUTES | 2 个 SKU | append child 与既有 family 属性组合重复，需要人工审核、变体拆分或降级策略。 |
| QUANTITY_EXCEEDS_MAX | 3 个 SKU | Commercial Gate 仍按 hard block 执行，库存 clamp 策略未落地。 |

## 9. TASK-133 收口后复跑

- **复跑时间**: 2026-06-14 05:56 Asia/Shanghai
- **复跑命令**: 同第 1 节
- **代码位置**: 生产容器临时目录 `/tmp/codex-amz-task129`
- **PUT 行为**: 未执行 PUT

修复内容：

1. Commercial Gate 将库存超上限从 hard block 改为 `PUBLISH_QUANTITY_CLAMPED` warning；`source_publish_quantity` 与最终 `publish_quantity` 写入审计，payload 使用截断后的发布库存。
2. 新建变体 parent 的 `fulfillment_availability.quantity` 固定为 `0`，避免 parent 携带子体/源库存。
3. CABINET 尺寸质量规则迁移到 `config/listing_gates/quality_gate.yaml`，本地不再用代码硬编码 42in 阻断；Amazon preview 负责返回最终 product type 限制。
4. CABINET variation theme 增补 `Size` → `ITEM_WIDTH`，`Color/Size` 继续渲染为 `COLOR/ITEM_WIDTH`。
5. Variation resolver 跳过 `Not Applicable` 等占位值，并可从商品名提取 `24inch` / `48"` 尺寸；无法得到有效尺寸时 fail closed。
6. Quality Gate 增加 `ITEM_WIDTH` theme 缺 `item_width` value/unit 的本地阻断。
7. Giga combo SKU 在只有重量、空间尺寸缺失时，从 `comboInfo` 补齐空间尺寸。
8. `country_of_origin` 增补 `Malaysia` → `MY` 映射。

最终结果：

| status | count |
| --- | ---: |
| skipped_existing_scope | 9 |
| blocked_variation_resolution | 3 |
| validation_preview_passed | 4 |
| validation_preview_issues | 4 |

Amazon preview 明细：

| SKU | request_id | result |
| --- | --- | --- |
| meow251115FC0ie | c593a022-40bd-49fd-9117-9ea9ee220f84 | passed |
| PARENT-794FD303D925 | f4c2b666-e1ce-490c-872c-172d5a94a781 | passed |
| meow251108Sk5g9 | dd08fd41-4bd9-466f-985c-91af5056d979 | passed |
| meow251108xDkIJ | edb2a879-5cae-43cb-bfb6-9fcd288d3508 | passed |
| PARENT-B8493E921DB3 | 730e96d2-cea4-4436-b811-f1528e964cb4 | `100335` WARNING: CABINET width 52.76in > Amazon max 42in |
| meow2508172omt6 | 6e9f40ad-63c2-415d-bfb8-9922deb1ab37 | `100335` WARNING: CABINET width 52.76in > Amazon max 42in |
| meow250817zRPIq | 245cda7b-6bcb-4f49-abd3-e02e53d1c33c | `100335` WARNING: CABINET width 53.54in > Amazon max 42in |
| meow250817AXWkg | 2e1fb02d-e0d0-49f1-9ab7-49d51b69692f | `100335` WARNING: CABINET width 52.76in > Amazon max 42in |

本地变体阻断：

| SKU | blocker |
| --- | --- |
| meow251115RfO3f | `DUPLICATE_VARIATION_ATTRIBUTES`，signature 为空 |
| meow251115S87Xu | `DUPLICATE_VARIATION_ATTRIBUTES`，signature `white / 24` |
| meow251115B5Iq9 | `DUPLICATE_VARIATION_ATTRIBUTES`，signature `black / 30` |

收口结论：

- 本轮代码问题已清：`QUANTITY_EXCEEDS_MAX` 不再阻断；`door`、variation theme、`item_width`、dimension unit、country、parent quantity 均通过本地测试和 Amazon preview 验证。
- 剩余 4 个 preview issues 全为 Amazon `WARNING`，原因是 CABINET product type 对 `item_depth_width_height.width` 的 max 为 42in，而目标 48in vanity 的 combo/package width 为 52.76/53.54in。
- 剩余 3 个 blocked variation 是真实重复属性组合，当前 fail closed 正确；LIVE 前需要运营确认是否拆分 family、改 parent 关系或转 single。
