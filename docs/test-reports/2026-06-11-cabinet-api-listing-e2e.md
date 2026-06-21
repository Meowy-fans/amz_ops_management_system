# CABINET API 发品端到端测试报告

- **报告日期**: 2026-06-11
- **执行环境**: 生产容器 `amz-listing-management-system`（镜像 `amz-listing-management-system:2026-06-09`）
- **测试类型**: 端到端 API 发品（非 Excel 链路）
- **目标品类**: CABINET
- **执行者**: Cursor Agent（用户监督）
- **关联任务**: Giga 收藏同步 → Amazon 未发品对比 → CABINET dry-run → 问题修复 → 正式部署 → LIVE 提交

> **用途说明**：本报告供 Codex 进行系统级优化输入，重点记录**观测事实、失败分层、根因假设与优化方向**，不预设实现方案。

---

## 1. 执行摘要

| 指标 | 结果 |
|------|------|
| Giga 收藏同步 | ✅ 349/349 成功 |
| API 未发品识别（18 个目标 SKU） | ✅ 流程可用 |
| CABINET dry-run | ✅ 可跑通，暴露 quality gate 问题 |
| 问题修复（fabric_type + 合规文案） | ✅ 9 个原阻断 SKU 通过本地 quality gate |
| 正式部署 fabric_type 修复 | ✅ `deploy/production/deploy.sh` 重建镜像 |
| CABINET LIVE 提交（`--no-dry-run`） | ⚠️ 流程跑通，**18 个目标 SKU 无一 `listing_confirmed`** |
| LIVE 全品类 create 提交（近 2h） | `blocked_quality_gate` 154 / `skipped_existing` 59 / `issues_found` 29 / `listing_confirmed` 0 |

**核心结论**：本地闸门（quality gate / commercial gate）与 Amazon 侧 schema 校验之间存在**显著 gap**；dry-run 通过 ≠ Amazon 可接受。系统需要把 Product Type Definitions schema 的必填字段覆盖、变体主题合法值、Commercial Gate 库存策略与发品目标对齐。

---

## 2. 测试环境与前置条件

### 2.1 基础设施

| 项 | 值 |
|----|-----|
| 项目路径 | `/home/liangqinhao/amz_listing_management_system` |
| 生产 compose | `/data/docker-compose/amz-listing-management-system/` |
| 数据库 | 共享 PostgreSQL，`amz_listing` 库 |
| Amazon API | SP-API Listings Items API（经 `AMAZON_HTTPS_PROXY` 出口） |
| Giga API | `product_list`（sort=4，收藏列表）+ `product_details` |

### 2.2 刻意选择的链路约束

- **不走 Excel 发品**：仅使用 `generate-listing-api`
- **不用离线报表查重**：未使用 `pending-statistics`（依赖 `amz_all_listing_report`）
- **查重事实源**：`searchListingsItems` cache + `getListingsItem`（与系统设计一致）

### 2.3 关键 CLI 命令

```bash
# Phase 1: Giga 收藏同步
python main.py --task sync-products --auto-confirm

# Phase 2: CABINET dry-run
python main.py --task generate-listing-api --category CABINET

# Phase 3: 正式部署
/home/liangqinhao/amz_listing_management_system/deploy/production/deploy.sh

# Phase 4: CABINET LIVE
python main.py --task generate-listing-api --category CABINET --no-dry-run
```

---

## 3. 测试阶段与结果

### Phase 1：Giga 收藏同步 + Amazon 未发品对比

#### 3.1.1 Giga 同步

| 指标 | 结果 |
|------|------|
| 命令 | `sync-products --auto-confirm` |
| Giga 收藏 SKU 数 | 349（API 分页 4 页） |
| 详情同步 | 349 成功 / 0 失败 |
| 耗时 | ~33s |

**观测问题（非阻断）**：CLI 结尾统计打印异常（`总计: total`），因 `handle_sync_products` 将 `sync_product_details()` 返回的 dict 当作 tuple 解包。日志中实际结果为 `总计349，成功349，失败0`。

#### 3.1.2 Amazon 未发品对比（API-native）

方法：

1. `AmazonPriceInventoryUpdateService._sync_listing_cache()` → `searchListingsItems`
2. 对 cache 未命中 SKU 执行 `AmazonListingSubmitter._get_existing_listing()`（404 = 未上架）

| 维度 | 数量 |
|------|------|
| DB 中 Giga SKU（历史累计） | 409 |
| 本次 API 拉取收藏 | 349 |
| 已有 meow_sku 映射 | 408 |
| Amazon listing cache（刷新后） | 344 |
| 已映射收藏 → cache 命中（已在 Amazon） | 273 |
| 已映射收藏 → cache 未命中 | 135 |
| GET 404 确认未上架 | 107 |
| GET 200 但 cache 未命中 | 28 |
| 本地 eligible 且 cache 未命中 | 126 |

**eligible 规则**（`get_pending_listing_skus`）：非超大件、GENERAL 卖家、`giga_product_base_prices.sku_available = TRUE`

#### 3.1.3 eligible 未发品按品类分布

| 标准品类 | 待发品数 | 备注 |
|---------|---------|------|
| (UNMAPPED) | 85 | 供应商品类未映射 |
| HOME_MIRROR | 21 | 有 API 模板 |
| CABINET | 18 | 有 API 模板 |
| OTTOMAN | 2 | 有映射、无 API 模板 |
| **合计** | **126** | |

可直接 API 发品：**CABINET 18 + HOME_MIRROR 21 = 39**

---

### Phase 2：CABINET dry-run

```bash
python main.py --task generate-listing-api --category CABINET
```

| 指标 | 结果 |
|------|------|
| 模式 | DRY RUN |
| 品类内待发 SKU（系统口径） | 278 |
| 处理结果总数 | 309（含 parent / pre-submit） |
| Submitter 层 quality gate BLOCK | 121 |
| commercial_gate 阻断（样例） | 5 |

**重要发现**：dry-run **不执行** `getListingsItem` 查重，会对已上架 SKU 仍构建 payload（与 LIVE 行为不同）。

#### 18 个目标 SKU dry-run 结果（修复前）

| 状态 | 数量 |
|------|------|
| dry_run 通过 | 9 |
| blocked_quality_gate | 9 |

9 个阻断 SKU 的一致原因：

| 阻断码 | 类型 | 说明 |
|--------|------|------|
| `MISSING_REQUIRED_ATTRIBUTE` | BLOCK | CABINET schema 必填 `fabric_type`，payload builder 未写入 |
| `PESTICIDE_CLAIM_RISK` | BLOCK | LLM 描述含 bacteria/mildew/mold |
| `AUTO_FILLED_RECOMMENDED_USE` | INFO | 非阻断，自动填 Bathroom |

---

### Phase 3：问题修复（B 方案）

#### 3.3.1 代码修复：`fabric_type`

**文件**: `src/services/amazon_listing_payload_builder.py`

**变更**: 为 CABINET 从 `Fabric Type` / `Main Material` / 默认 `Wood` 推导并写入 `fabric_type`。

**单测**: `tests/unit/services/test_amazon_listing_payload_builder.py` 通过。

#### 3.3.2 内容修复：9 个 vendor SKU 重生成

**方法**: `ProductDetailGenerationService.process_skus()` + `ComplianceClaimScanner`

| vendor SKU | 合规扫描 |
|------------|---------|
| W3133S00011, W3151S00047, W3151S00048, W3151S00054, W3520S00009, N817P339017B, N725P314023F, W3151S00056, N710P291684C | 9/9 PASS |

#### 3.3.3 修复后本地验证

对 9 个原阻断 meow SKU 重建 plan + quality gate：**9/9 PASS，0 BLOCK**。

---

### Phase 4：正式部署

```bash
/home/liangqinhao/amz_listing_management_system/deploy/production/deploy.sh
```

| 项 | 结果 |
|----|------|
| 镜像 | `amz-listing-management-system:2026-06-09` 重建 |
| 容器 | 4 个全部重启，主服务 healthy |
| fabric_type 修复 | 容器内已确认存在 |

**未提交 Git**：`amazon_listing_payload_builder.py` 与单测文件在工作区有修改（`git status` 显示 `M`）。

---

### Phase 5：CABINET LIVE 提交

```bash
python main.py --task generate-listing-api --category CABINET --no-dry-run
```

| 指标 | 结果 |
|------|------|
| 模式 | LIVE |
| 耗时 | ~212s |
| 处理结果总数 | 309 |
| Submitter 汇总 | `ok=0 fail=0 with_issues=0`（121 SKUs 层） |

#### LIVE create 提交统计（2026-06-11 09:00+，`amazon_api_submissions`）

| status | count |
|--------|------:|
| blocked_quality_gate | 154 |
| skipped_existing | 59 |
| issues_found | 29 |
| listing_confirmed | **0** |

---

## 4. 18 个目标 SKU 最终结果矩阵

| meow_sku | giga_sku | LIVE 结果 | 说明 |
|----------|----------|-----------|------|
| meow251115VtNnK | N725P314023F | skipped_existing | GET 200，已在 Amazon |
| meow251115ZHPrR | W3151S00056 | skipped_existing | GET 200，已在 Amazon |
| meow251115x6Wq1 | N710P291684C | skipped_existing | GET 200，已在 Amazon |
| meow250817zRPIq | W3133S00011 | issues_found | Amazon 校验拒绝（15–17 issues） |
| meow251108Sk5g9 | W3151S00047 | issues_found | Amazon 校验拒绝 |
| meow251108xDkIJ | W3151S00048 | issues_found | Amazon 校验拒绝 |
| meow251115B5Iq9 | W3151S00054 | issues_found | Amazon 校验拒绝 |
| meow251115FC0ie | W3520S00009 | issues_found | Amazon 校验拒绝 |
| meow251115RfO3f | N817P339017B | issues_found | Amazon 校验拒绝 |
| meow2508172omt6 | W3133S00002 | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow250817AXWkg | W3133S00001 | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow2511152QcBq | N710P191970C | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow2511152dapi | N710P191970M | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow251115FUUlt | W3151S00055 | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow251115IhvcJ | N759P346895B | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow251115S87Xu | N710S324097K | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow251115aI4LD | N710P324097K | blocked_commercial_gate | `QUANTITY_EXCEEDS_MAX` |
| meow251115zg0HP | N729P170388B | blocked_variation_resolution | `NO_ELIGIBLE_VARIATION_THEME` |

**汇总**：已在 Amazon 3 / Amazon 拒绝 6 / Commercial Gate 8 / 变体阻断 1 / **新上架确认 0**

---

## 5. 失败根因分析（供优化参考）

### RC-01：本地 quality gate 与 Amazon schema 必填字段不同步

**现象**

- 修复 `fabric_type` 后，9 个 SKU 本地 quality gate 全部 PASS
- 同批 6 个 SKU LIVE PUT 后 `issues_found`，Amazon 返回大量 `90220`（Required attribute missing）

**Amazon 侧缺失属性（6 个 issues_found SKU 共性，按出现频次）**

| 属性 | 出现次数（约） |
|------|---------------|
| mounting_type | 6 |
| model_name | 6 |
| construction_type | 6 |
| number_of_items | 6 |
| door | 6 |
| special_feature | 6 |
| included_components | 6 |
| is_assembly_required | 6 |
| item_shape | 6 |
| room_type | 6 |
| is_fragile | 6 |
| number_of_drawers | 6 |
| variation_theme | 4（90244：Color 值非法） |
| item_depth_width_height | 1 |
| item_weight | 1 |

**样例 issue**（`meow251108Sk5g9`）：

```json
{"code": "90220", "message": "'Required Assembly' is required but missing.", "attributeNames": ["is_assembly_required"]}
{"code": "90244", "message": "We can't accept the Color you entered for Variation Theme Name...", "attributeNames": ["variation_theme"]}
{"code": "90000900", "message": "You submitted an attribute Item Type Name that does not belong...", "attributeNames": ["item_type_name"]}
```

**根因假设**

1. `AmazonListingQualityGate._validate_cached_required_fields` 依赖 `schema_service.get_cached_schema()` 的 `required_properties`，但 CABINET cached schema 可能不完整，或未与 Amazon 实时校验一致
2. `AmazonListingPayloadBuilder` 仅映射少量通用字段（title/bullets/color/material/dimensions 等），**未覆盖 CABINET 品类大量必填属性**
3. `sp_api_cabinet.json` 映射中有 `Fabric Type`、`Door Style` 等，但 **API-native builder 路径未使用该映射层**（Excel 路径与 API 路径分叉）
4. OTTOMAN E2E 验收（`docs/acceptance/ottoman-e2e-2026-05-18.md`）曾验证 `fabric_type` 等字段，但 **CABINET API builder 未复用同等深度的属性映射**

**优化方向**

- API payload 构建应 schema-driven：从 cached Product Type Definitions 拉取 required + 从 Giga/LLM 数据填充
- quality gate 的 required 检查应与 Amazon `VALIDATION_PREVIEW` 或 PUT 返回的 issues 闭环
- 统一 Excel 映射配置（`config/amz_listing_data_mapping/`）与 API builder 的数据源

---

### RC-02：dry-run 与 LIVE 行为不一致，导致误判「可提交」

**现象**

- 9 个 SKU 在 dry-run 中状态为 `dry_run`（2026-05-17 历史记录），本次 LIVE 未更新其 submission 记录
- LIVE 时这 9 个被 `blocked_commercial_gate` 或 `blocked_variation_resolution` 在 **plan 构建阶段**拦截，未进入 submitter

**根因**

1. dry-run 不执行 `getListingsItem` 查重 → 已上架 SKU 仍显示「可预览」
2. dry-run 不执行 commercial gate 的 LIVE 同等策略（或 dry-run 时 gate 结果未写入 `amazon_api_submissions`）
3. `pre_submit_results`（commercial/variation block）**不持久化**到 `amazon_api_submissions`，难以审计

**优化方向**

- dry-run 应可选启用查重只读检查
- 所有 block 状态（commercial / variation / quality）统一写入 audit 表
- CLI 输出应区分「历史 dry_run」与「本次运行结果」

---

### RC-03：Commercial Gate 库存上限与「可发品」统计口径冲突

**现象**

- 8 个曾 dry-run 通过的 SKU，LIVE 全部被 `QUANTITY_EXCEEDS_MAX` 拦截
- 配置：`config/listing_gates/commercial_gate.yaml` → CABINET `max_publish_quantity: 10`

**根因**

- `get_pending_listing_skus` / eligible 统计**不考虑** commercial gate 库存上限
- 用户看到的「18 个 eligible 未发品」中，有 8 个实际上永远无法进入 PUT（除非库存下降或配置调整）
- commercial gate 使用 `giga_inventory.quantity`，可能与 Amazon 发布库存策略（cap 到 10）未在统计层体现

**优化方向**

- eligible 统计应叠加 commercial gate 预检
- 或在 gate 中对超限库存 **clamp 到 max_publish_quantity** 而非 hard block（需业务确认）
- Web/CLI 应展示 `publish_quantity` 与 `source_quantity` 分离

---

### RC-04：变体主题解析失败

**现象**

- `meow251115zg0HP` → `blocked_variation_resolution` / `NO_ELIGIBLE_VARIATION_THEME`

**根因假设**

- `AmazonVariationResolver` 无法从 Giga 关联 SKU / 历史家族 / 属性组合中确定合法 variation theme
- 可能与 associateProductList 缺失、属性重复、或 theme 与 Amazon valid values 不匹配有关

**优化方向**

- 审计 `amazon_variation_resolution_runs` 表（如有记录）获取阻断详情
- 对无法解析的 SKU 提供降级为 SINGLE 或人工指定 theme 的 escape hatch

---

### RC-05：合规扫描与 LLM 内容管线（已部分修复）

**现象（修复前）**

- 9 个 SKU 因 `PESTICIDE_CLAIM_RISK` 阻断（bacteria/mildew/mold）

**已执行修复**

- `ProductDetailGenerationService.process_skus()` 重生成 9 个 vendor SKU → 全部合规 PASS

**残留风险**

- LLM 仍可能生成触发 `ComplianceClaimScanner` 的词汇；需在生成阶段强制 `scan_and_sanitize` 而非仅在 quality gate 阻断
- `ProductContentGenerator` 已有 compliance pipeline，但历史内容未批量回溯更新

---

### RC-06：`fabric_type` 缺失（已修复，需固化）

**现象（修复前）**

- CABINET schema `required_properties` 含 `fabric_type`，API builder 未写入

**已执行修复**

- `AmazonListingPayloadBuilder._set_fabric_type()` 已加入并部署

**残留**

- Git 未提交；需纳入正式版本与 CI
- `fabric_type` valid values 未从 schema 对齐（`get_cached_valid_values` 返回 None）

---

### RC-07：Amazon cache 与 GET 查重不一致

**现象（Phase 1）**

- 28 个 SKU：cache 未命中，但 `getListingsItem` 返回 200

**根因假设**

- `searchListingsItems` 分页/参数导致 cache 不完整
- GET 查重可兜底，但 cache 用于统计时会低估「已上架」数量

**优化方向**

- 发品前强制 refresh cache 或统计层统一以 GET 为准
- 调查 `searchListingsItems` 翻页是否遗漏 SKU

---

### RC-08：品类任务范围过大，结果难解读

**现象**

- `generate-listing-api --category CABINET` 处理 278 个待发 SKU，而非仅 18 个目标
- LIVE 输出 `309` 条结果，用户难以聚焦目标 SKU

**优化方向**

- 支持 `--sku` / `--sku-file` 过滤
- 或 `--only-not-on-amazon` 仅处理 cache+GET 确认未上架的 SKU

---

### RC-09：CLI / 可观测性缺陷

| 问题 | 位置 | 影响 |
|------|------|------|
| sync-products 统计打印错误 | `handle_sync_products` | 误导运维 |
| `pending-statistics` 仍用离线报表 | `query_handlers.py` | 与 API 链路口径不一致 |
| LIVE 汇总 `ok=0` 不直观 | submitter reporter | 难以判断成功率 |
| commercial/variation block 无 DB 审计 | `product_listing_api_plan_builder` | 无法 SQL 追溯 |

---

## 6. 已修改文件清单（本次测试产生）

| 文件 | 变更 | 状态 |
|------|------|------|
| `src/services/amazon_listing_payload_builder.py` | 新增 `_set_fabric_type` | 已部署，未 git commit |
| `tests/unit/services/test_amazon_listing_payload_builder.py` | 补充 fabric_type 断言 | 已修改，未 git commit |
| `ds_api_product_details`（9 行） | LLM 内容重生成 | DB 已更新 |
| `amazon_api_submissions` | LIVE 新增 ~242 条 create 记录 | DB 已写入 |

---

## 7. 推荐优化优先级（给 Codex）

| 优先级 | 主题 | 预期收益 |
|--------|------|---------|
| **P0** | CABINET API payload schema 全覆盖（required 属性从 PTDS 驱动） | 解决 6 个 issues_found 主因 |
| **P0** | quality gate 与 Amazon VALIDATION_PREVIEW / PUT issues 对齐 | 避免「本地 PASS、Amazon FAIL」 |
| **P1** | commercial gate 与 eligible 统计口径统一；库存 clamp vs block 策略 | 解决 8 个 QUANTITY_EXCEEDS_MAX |
| **P1** | variation_theme 合法值校验 + resolver 降级路径 | 解决 1 个变体阻断 |
| **P1** | 统一 Excel 映射与 API builder 数据源 | 消除双轨分叉 |
| **P2** | dry-run 增强（查重只读、block 持久化） | 提升测试可信度 |
| **P2** | CLI 支持 SKU 级过滤 + 统计修复 | 提升可操作性 |
| **P2** | listing cache 完整性 | 统计更准确 |

---

## 8. 参考文档与代码入口

| 资源 | 路径 |
|------|------|
| 本报告 | `docs/test-reports/2026-06-11-cabinet-api-listing-e2e.md` |
| OTTOMAN 成功验收（对照） | `docs/acceptance/ottoman-e2e-2026-05-18.md` |
| API 发品 plan 构建 | `src/services/product_listing_api_plan_builder.py` |
| Payload 构建 | `src/services/amazon_listing_payload_builder.py` |
| Quality gate | `src/services/amazon_listing_quality_gate.py` |
| Commercial gate 配置 | `config/listing_gates/commercial_gate.yaml` |
| CABINET 字段映射 | `config/amz_listing_data_mapping/sp_api_cabinet.json` |
| 合规扫描 | `src/services/compliance_claim_scanner.py` |
| LIVE 日志（宿主机） | `/tmp/cabinet-listing-live.log` |
| dry-run 日志（宿主机） | `/tmp/cabinet-listing-dryrun.log` |

---

## 9. 附录：测试时间线

| 时间 (UTC+8) | 事件 |
|--------------|------|
| 2026-06-11 ~13:38 | Giga sync-products 349/349 |
| 2026-06-11 ~13:42 | API 对比：126 eligible 未上架，CABINET 18 |
| 2026-06-11 ~17:13 | CABINET dry-run，9/18 quality gate 阻断 |
| 2026-06-11 ~17:30 | fabric_type 修复 + 9 SKU 内容重生成，quality gate 9/9 PASS |
| 2026-06-11 ~18:15 | deploy.sh 重建镜像 |
| 2026-06-11 ~18:22–18:25 | CABINET LIVE，`listing_confirmed=0` |

---

## 10. 验收结论

本次测试**成功验证了 API 发品链路的可执行性**（Giga → plan → gate → PUT → audit），但**未达到业务目标**（18 个 CABINET 目标 SKU 无一新上架确认）。

主要阻断已从「本地文案/单字段」升级为「**Amazon schema 必填字段系统性缺失**」与「**Commercial Gate 与发品统计口径不一致**」。建议 Codex 以 **RC-01（schema 全覆盖）** 和 **RC-03（commercial gate 策略）** 为优化主线，参照 OTTOMAN 成功验收路径补齐 CABINET API-native 属性映射深度。
