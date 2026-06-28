# 退役计划：Listing Requirement & Payload Engine V2 切换

**创建日期**: 2026-06-27
**负责人**: Codex
**目标完成**: 2026-07-31

## 背景

当前 API-native 发品链路的属性解析、payload 渲染、coverage 和 review 仍以平面属性为核心；V2 已建立 RequirementTree / ResolutionTree / PayloadBuildPlan，用于支持条件 required、object 子字段、path-level confidence/review 和通用 object payload。切换必须经过 shadow 与 strict-preview regression，不允许直接替换 LIVE。

## 新增模块

| 模块 | 路径 | 职责 |
|------|------|------|
| Requirement V2 contracts | `src/services/requirement_models_v2.py` | RequirementTree / ResolutionTree / PayloadBuildPlan 数据契约 |
| Schema condition evaluator V2 | `src/services/schema_condition_evaluator_v2.py` | 条件 required 保守求值与 trace |
| Requirement tree builder V2 | `src/services/requirement_tree_builder_v2.py` | 构建 applicable required tree，注入 learned required paths |
| Evidence resolver V2 | `src/services/evidence_resolver_v2.py` | path/default/review_override/LLM source 解析 |
| LLM extractor V2 | `src/services/llm_attribute_extractor_v2.py` | path-level evidence-bound LLM 提取 |
| Confidence scorer V2 | `src/services/confidence_scorer_v2.py` | path-level confidence 评分和 parent aggregation |
| Payload composer V2 | `src/services/payload_composer_v2.py` | 通用 list/object/nested_object/measure/array_object payload 渲染 |
| Coverage gate V2 | `src/services/coverage_gate_v2.py` | tree-level required coverage、review、confidence、safe default gate |
| Review adapter V2 | `src/services/review_adapter_v2.py` | path-level pending review 持久化、审核、override replay |
| Validation preview V2 | `src/services/validation_preview_v2.py` | V2 Amazon VALIDATION_PREVIEW 审计与 comparison |
| Feedback learning V2 | `src/services/feedback_learning_adapter_v2.py` | Amazon 90220 path_key 粒度学习 |
| Shadow adapter V2 | `src/services/listing_payload_shadow_adapter_v2.py` | V1 旁路运行 V2，并写 shadow audit |
| Shadow diff V2 | `src/services/listing_payload_shadow_diff_v2.py` | 读取 shadow audit，产出 V1/V2 diff 摘要 |
| Regression evaluator V2 | `src/services/listing_payload_v2_regression.py` | S14 多类目 shadow 证据 go/no-go 评估 |
| Engine V2 | `src/services/listing_payload_engine_v2.py` | V2 read-only requirement + payload build orchestration |

## 退役模块（迁移完成后删除）

| 模块 | 路径 | 行数 | 依赖方 | 备注 |
|------|------|------|--------|------|
| AttributeResolver | `src/services/attribute_resolver.py` | 待测 | `AmazonListingPayloadBuilder` / V1 coverage / review pipeline | V2 parity 证明前不加 `@retire`，cutover 后按独立 PR 标记 |
| AttributePayloadRenderer | `src/services/attribute_payload_renderer.py` | 待测 | `AmazonListingPayloadBuilder` | V2 `PayloadComposerV2` 替代 |
| AmazonListingAttributeCoverageGate | `src/services/amazon_listing_attribute_coverage_gate.py` | 待测 | `ProductListingAPIPlanBuilder` | V2 `CoverageGateV2` 替代 |
| ConfidenceScorer V1 | `src/services/confidence_scorer.py` | 待测 | V1 review pipeline | V2 path-level scorer 替代；V1 review 表保留到 cutover 后 |
| ReviewManager / V1 pending review path | `src/services/review_manager.py` 等 | 待测 | `review-pending-attributes --engine v1` | V2 review adapter 证明 resume parity 后再退役 |

## 需要重构的混合模块

| 模块 | 当前行数 | 变更描述 | 预计行数变化 |
|------|----------|----------|-------------|
| `src/services/product_listing_api_plan_builder.py` | 待测 | 将 `LISTING_PAYLOAD_ENGINE=v2` 从 shadow-only 扩展为可替换 V1 payload/coverage 决策；默认继续 `v1`，cutover 后反转默认值 | 小幅增加，后续删除 V1 分支后下降 |
| `src/services/amazon_listing_payload_builder.py` | 待测 | V2 cutover 后只保留非属性类组装职责，属性 resolver/renderer 移交 V2 | 下降 |
| `src/cli/operation_handlers.py` | 1525+ | S14 前拆出 `operation_handlers_v2.py` 承载 V2 CLI，解决文件规模红线 | 主文件下降 |
| `src/cli/task_dispatcher.py` | 待测 | 注册 V2 regression/cutover CLI；cutover 后保留 V1 fallback task 到观察期结束 | 小幅变化 |

## 不再使用的数据

| 资源 | 类型 | 说明 |
|------|------|------|
| `amz_listing_pending_review` | 表 | V1 SKU-level review 表；V2 稳定后由 `amz_listing_pending_review_v2` 替代，删除前需导出/归档未完成 review |
| V1 learned required feedback in `amazon_api_submissions` | 历史数据 | 保留为审计，不再作为 V2 required source；V2 使用 `amz_listing_learned_required_paths_v2` |
| V1 attribute rule YAML 中的纯属性补丁 | 配置 | cutover 后仍可作为 source rules 输入，但不再承担最终 coverage/payload rendering 语义 |

## S14 Go/No-Go 检查清单

- [x] `generate-listing-api --engine shadow`（或 `LISTING_PAYLOAD_ENGINE=shadow`）已对 CABINET / HOME_MIRROR / OTTOMAN 选定 SKU 跑完 dry-run，不改变 LIVE
- [x] CABINET 最新 shadow evidence 无 V2 blocking：`meow251115FC0ie` latest submission `114150`，V2 attrs=31，missing=0，pending=0，blocking=0；`LISTING_V2_REGRESSION_LIMIT=1 evaluate-listing-v2-regression --category CABINET` 返回 `go`。报告：`docs/test-reports/2026-06-27-listing-payload-v2-cabinet-shadow.md`
- [x] `report-listing-shadow-diff-v2` 显示 HOME_MIRROR / OTTOMAN 无 V2 blocking 或有明确豁免记录：HOME_MIRROR `115998` missing=0/pending=0/blocking=0；OTTOMAN latest per SKU rows `116003` / `116002` missing=0/pending=0/blocking=0
- [x] `evaluate-listing-v2-regression` 对 HOME_MIRROR / OTTOMAN 返回 `go`
- [x] CHAIR / SOFA shadow 失败均可解释为 missing evidence、pending review、unsafe default 或真实 schema requirement；SOFA 另有 direct V2 read-only plan after seat-rule fix：missing=0，仅 `seating_capacity.value` / `sofa_type.value` pending review
- [x] `LISTING_PAYLOAD_ENGINE=v2` authoritative dry-run canary path 已实现；LIVE `--no-dry-run` 仍阻断
- [x] CABINET `meow251115FC0ie` 已跑 `generate-listing-api --engine v2 --strict-validation`，进入 V2 authoritative submitter path 后因 Amazon 已存在返回 `skipped_existing`，无 PUT；`MISSING_MAIN_IMAGE` 兼容缺口已修复
- [x] HOME_MIRROR `meow251108CqW5i` 已跑 `generate-listing-api --engine v2 --strict-validation`，进入 V2 authoritative submitter path 后因 Amazon 已存在返回 `skipped_existing`，无 PUT
- [x] OTTOMAN `meow2511088jSUW` / `meow260518LZZCw` 已跑 V2 authoritative strict-validation，新 parent `PARENT-818700D0BEB9` Amazon `VALIDATION_PREVIEW` passed（0 issues），children skipped existing，无 PUT
- [x] `validate-listing-v2` / authoritative strict-validation 对代表 SKU 完成 Amazon VALIDATION_PREVIEW（无 PUT），并持久化 audit：OTTOMAN parent `PARENT-818700D0BEB9`
- [x] `ValidationPreviewV2.compare()` 无不可解释 Amazon-only issue；`evaluate-listing-v2-validation-compare` 对 CABINET / HOME_MIRROR / OTTOMAN canary SKU 返回 `go`（需同时挂载 `.env.amazon-sp-api`）。报告：`docs/test-reports/2026-06-27-listing-payload-v2-validation-compare.md`
- [x] V2 review resume：pending -> AI/human decision -> override replay 已通过至少 1 个 SKU smoke（SOFA `meow251108Bg4d4`；报告：`docs/test-reports/2026-06-27-listing-payload-v2-review-resume-smoke.md`）
- [x] `operation_handlers_v2.py` 已收纳 V2 CLI（314 行）；`operation_handlers.py` 仍 1432 行，超 500 红线，需后续继续拆分 V1 handler
- [ ] 旧模块 `@retire` 标记只在 parity 证明后添加，且 scheduled removal 明确
- [x] V2/CLI/service/builder/tree targeted regression 通过：167 passed；ruff 和 `git diff --check` 通过。全量 suite 未在本 slice 重跑

## 退役检查清单

- [ ] 所有退役模块的 import 引用已确认清零
- [ ] 配置文件中的引用已清理
- [ ] deploy/docker-compose 中的引用已清理
- [ ] CLI task 已在 task_dispatcher 中取消注册
- [ ] CI 全量测试通过
- [ ] 生产冒烟测试通过
- [ ] 退役 PR 已独立提交（与功能 PR 分开）
- [ ] 相关文档已更新（README / architecture.md / STATUS.md）

## 执行策略

1. 观察期内默认 `LISTING_PAYLOAD_ENGINE=v1`。
2. `--engine shadow` / `LISTING_PAYLOAD_ENGINE=shadow` 用于 V1 authoritative + V2 audit，不改变 V1 决策。
3. `--engine v2` / `LISTING_PAYLOAD_ENGINE=v2` 当前只允许 dry-run / strict-validation authoritative canary；LIVE `--no-dry-run` 必须继续由 CLI 和 service 双层阻断。
4. CABINET / HOME_MIRROR / OTTOMAN 已完成首轮 V2 authoritative strict-preview parity；下一步先完成 V2 path-level review resume smoke。
5. Review resume 与更多 canary evidence 通过后，再选择单类目、单 SKU 范围做 V2 LIVE canary。
6. Canary 成功后按类目逐步放量；每一步保留环境变量回滚到 `v1`。
7. V2 稳定后单独提交退役 PR，添加 `@retire` 标记，再按 scheduled removal 删除 V1 模块。
