# 退役计划：Excel 新品发品流程

**创建日期**: 2026-06-15
**负责人**: Codex
**目标完成**: 2026-07-31

## 背景

新品发品主路径已切到 API-native `generate-listing-api`，Excel 生成、模板解析和模板纠错链路不再符合多类目规模化运营与 Amazon schema/API 预检闭环要求，需要独立退役并避免继续承载新功能。

## 新增模块

| 模块 | 路径 | 职责 |
|------|------|------|
| ProductListingAPIPlanBuilder | `src/services/product_listing_api_plan_builder.py` | 从商品数据直接构建 API-native 发品计划 |
| AmazonListingDraftBuilder | `src/services/amazon_listing_draft_builder.py` | 构建发品 draft，不生成 Excel-like 中间行 |
| AmazonListingPayloadBuilder | `src/services/amazon_listing_payload_builder.py` | 渲染 Listings Items API payload |
| AmazonVariationResolver | `src/services/amazon_listing_variation_payload.py` | 基于配置和历史家族解析 variation theme |
| AttributeRuleLoader / AttributeResolver | `src/services/attribute_rule_loader.py`, `src/services/amazon_attribute_resolver.py` | 基于 Product Type schema 与 YAML 规则解析属性 |
| AmazonListingSubmitter | `src/services/amazon_listing_submitter.py` | 执行 dry-run、strict validation、LIVE 提交与审计 |

## 退役模块（迁移完成后删除）

| 模块 | 路径 | 行数 | 依赖方 | 备注 |
|------|------|------|--------|------|
| ExcelGenerator | `src/utils/excel_generator.py` | 约 200 | legacy `generate_listings_by_category`、旧测试 | 仅保留历史 Excel 生成与排障参考 |
| AdvancedTemplateParser | `src/services/amz_template_parser.py` | 约 285 | legacy template-update、旧测试 | Product Type Definitions + YAML 规则替代 |
| Template parser helpers | `src/services/template_parser_helpers.py` | 约 150 | `amz_template_parser.py`、旧测试 | 随模板解析器一起退役 |
| TemplateManagementService | `src/services/amz_template_management_service.py` | 约 290 | legacy template-update/template-correction、旧测试 | 不再作为类目接入路径 |
| Template rule correction | `src/services/amz_template_rule_correction.py` | 约 100 | legacy template-correction、旧测试 | strict validation issues + 配置规则替代 |
| Template variation config | `src/services/template_variation_config.py` | 约 130 | legacy template-update、旧测试 | `AmazonVariationResolver` 替代 |
| ProductListingVariationBuilder | `src/services/product_listing_variation_builder.py` | 约 160 | Excel row path、旧测试 | API-native plan builder 替代 |

## 需要重构的混合模块

| 模块 | 当前行数 | 变更描述 | 预计行数变化 |
|------|----------|----------|-------------|
| `src/services/product_listing_service.py` | 约 360 | 删除 `_build_rows_for_category`、`generate_listings_by_category`、Excel row 处理和 `ExcelGenerator` / `AmzTemplateRepository` 依赖，仅保留 API-native 编排 | -120 到 -180 |
| `src/cli/listing_handlers.py` | 约 150 | 删除 `handle_generate_listing_excel_deprecated`；`handle_generate_listing` deprecated alias 可在兼容窗口后移除 | -40 到 -70 |
| `src/cli/task_dispatcher.py` | 约 130 | 兼容窗口结束后取消 `generate-listing` 注册，只保留 `generate-listing-api` | -5 到 -10 |
| `tests/` legacy Excel/template tests | 多文件 | 删除或迁移旧 Excel/template 测试；保留 API-native replacement tests | 视删除范围而定 |

## 不再使用的数据

| 资源 | 类型 | 说明 |
|------|------|------|
| `template_files/` | 目录 | Amazon Excel 模板归档，仅保留到退役窗口结束 |
| `output/*.xlsm` | 目录/文件 | Excel 发品输出，不再由新品发品流程生成 |
| `amazon_cat_templates` | 表 | legacy 模板规则缓存；API-native 发品不再依赖，删除前需确认查询与历史报表无运行时依赖 |
| `category_details.template` | 配置字段 | legacy Excel 模板路径字段；删除前需确认没有非发品流程复用 |

## 退役检查清单

- [x] 所有退役模块已加机器可读 `@retire` 标记
- [x] API-native `generate-listing-api` 已成为 README 和菜单中唯一新品发品入口
- [x] `generate-listing` 不再生成 Excel，当前仅作为 deprecated dry-run alias
- [x] Excel 退役计划已独立成文
- [ ] 所有退役模块的 import 引用已确认清零
- [ ] 配置文件中的引用已清理
- [ ] deploy/docker-compose 中的引用已清理
- [ ] CLI task 已在 task_dispatcher 中取消注册
- [x] CI 全量测试通过
- [x] 生产冒烟测试通过
- [ ] 退役 PR 已独立提交（与功能 PR 分开）
- [x] 相关文档已更新（README / architecture.md / STATUS.md）

## 执行策略

1. 当前阶段只做标记、文档和入口降噪，不删除仍被测试覆盖的 legacy 模块。
2. 在 CABINET 和至少一个非 CABINET 类目 API-native strict dry-run 验收通过后，删除 Excel row path 和对应测试。
3. 删除 `amazon_cat_templates` 前先做数据库引用审计，避免影响历史查询或运营报表。
