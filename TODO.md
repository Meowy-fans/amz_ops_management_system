# Project Todo

## 规范化改造任务

| ID | 标题 | 优先级 | 状态 | 负责人 | 关联需求 | 预计完成 | 实际完成 | 验证证据 |
|----|------|--------|------|--------|----------|----------|----------|----------|
| TASK-001 | 规范化项目根目录结构 | P0 | ✅ | Antigravity | Phase 1 | 2026-02-19 | 2026-02-19 | 目录结构已调整 |
| TASK-002 | 创建 STATUS.md 和 TODO.md | P0 | ⏳ | Antigravity | Phase 1 | 2026-02-19 | - | 本文件 |
| TASK-003 | 补充 docs/architecture.md | P1 | 🔲 | Antigravity | Phase 1 | 2026-02-19 | - | - |
| TASK-004 | 搭建 pytest 测试框架 | P0 | ✅ | Antigravity | Phase 2 | 2026-02-20 | 2026-02-20 | pytest运行正常 |
| TASK-005 | 编写 utils 模块单元测试 | P0 | ✅ | Antigravity | Phase 2 | 2026-02-20 | 2026-02-20 | 覆盖率满足 |
| TASK-006 | 编写 services 模块单元测试 | P1 | ✅ | Antigravity | Phase 2 | 2026-02-21 | 2026-02-21 | - |
| TASK-007 | 编写 repositories 集成测试 | P1 | ✅ | Antigravity | Phase 2 | 2026-02-21 | 2026-02-21 | 改为Mock测试 |
| TASK-008 | 创建 docker-compose.yml | P1 | ✅ | Antigravity | Phase 3 | 2026-02-22 | 2026-02-22 | 文件已创建 |
| TASK-009 | 创建 deploy.sh 部署脚本 | P1 | ✅ | Antigravity | Phase 3 | 2026-02-22 | 2026-02-22 | 脚本已测试 |
| TASK-010 | 引入 Alembic 数据库迁移 | P1 | ✅ | Antigravity | Phase 4 | 2026-02-23 | 2026-02-23 | 初始脚本已创建 |
| TASK-011 | 配置 Pre-commit Hooks | P2 | ✅ | Antigravity | Phase 4 | 2026-02-23 | 2026-02-23 | 配置文件已创建 |
| TASK-012 | Pydantic BaseSettings 配置 | P2 | ✅ | Antigravity | Phase 4 | 2026-02-24 | 2026-02-24 | 已重构所有配置 |
| TASK-013 | Giga Sync 单元测试 | P1 | ✅ | Antigravity | Phase 5 | 2026-02-24 | 2026-02-24 | 已完成 |
| TASK-014 | Pricing Service 单元测试 | P1 | ✅ | Antigravity | Phase 5 | 2026-02-24 | 2026-02-24 | 已完成 |
| TASK-015 | Category Service 单元测试 | P2 | ✅ | Antigravity | Phase 5 | 2026-02-24 | 2026-02-24 | 已完成 |
| TASK-016 | 集成测试环境配置 | P1 | ⏳ | Antigravity | Phase 5 | 2026-02-25 | - | - |
| TASK-017 | Repository 集成测试 | P1 | 🔲 | Antigravity | Phase 5 | 2026-02-26 | - | - |
| TASK-018 | 修复正式测试文件被 `.gitignore` 屏蔽 | P0 | ✅ | Codex | 偏移缓解 Phase 0 | 2026-05-04 | 2026-05-04 | `.gitignore` 改为仅忽略根目录临时 `test_*.py` |
| TASK-019 | 修复 `GigaInventorySyncService` 单测挂起 | P0 | ✅ | Codex | 偏移缓解 Phase 0 | 2026-05-04 | 2026-05-04 | `pytest` 完整通过：52 passed |
| TASK-020 | 建立当前覆盖率基线 | P0 | ✅ | Codex | 偏移缓解 Phase 0 | 2026-05-04 | 2026-05-04 | `pytest --cov=src --cov=infrastructure`: 60.60% |
| TASK-021 | 接入 GitHub Actions self-hosted runner CI | P0 | ✅ | Codex | 偏移缓解 Phase 2 | 2026-05-05 | 2026-05-04 | repo-level runner `amz-listing-runner-01` online；CI run `25330003050` 在 commit `c5dc219` 绿色通过 |
| TASK-022 | 补关键模块设计文档 | P1 | ✅ | Codex | 偏移缓解 Phase 1 | 2026-05-05 | 2026-05-04 | 已新增 `docs/module-design/` 4 篇与 `docs/api-contracts/service-results.md` |
| TASK-023 | 拆分 `main.py` CLI/任务路由/应用任务边界 | P1 | ✅ | Codex | 偏移缓解 Phase 3 | 2026-05-06 | 2026-05-04 | 已拆出菜单、查询、类目配置、发品、运营 handler 和任务注册；`main.py` 当前 96 行 |
| TASK-024 | Service 层去展示化：PricingService reporter 边界 | P1 | ✅ | Codex | 偏移缓解 Phase 4 | 2026-05-06 | 2026-05-04 | `PricingService` 支持 `NullPricingProgressReporter` 并复用统一 reporter；`pytest`: 78 passed |
| TASK-025 | Service 层去展示化：Giga 同步/库存/价格输出边界 | P1 | ✅ | Codex | 偏移缓解 Phase 4 | 2026-05-07 | 2026-05-04 | `GigaSyncService`/`GigaInventorySyncService`/`GigaPriceSyncService` 支持可替换 reporter；`pytest`: 78 passed |
| TASK-026 | Service 层去展示化：库存价格更新编排服务输出边界 | P1 | ✅ | Codex | 偏移缓解 Phase 4 | 2026-05-07 | 2026-05-04 | `InventoryPriceUpdaterService` 支持可替换 reporter 并传递给子服务；`pytest`: 78 passed |
| TASK-027 | Service 层去展示化：AI 商品详情生成输出边界 | P1 | ✅ | Codex | 偏移缓解 Phase 4 | 2026-05-07 | 2026-05-04 | `ProductDetailGenerationService` 支持可替换 reporter；`pytest`: 78 passed |
| TASK-028 | Service 层去展示化：品类维护输出边界 | P1 | ✅ | Codex | 偏移缓解 Phase 4 | 2026-05-07 | 2026-05-04 | `CategoryMaintenanceService` 支持可替换 reporter；`pytest`: 78 passed |
| TASK-029 | Service 层去展示化：全量报告导入与发品状态更新输出边界 | P1 | ✅ | Codex | 偏移缓解 Phase 4 | 2026-05-07 | 2026-05-04 | `AmzFullListImporterService` 与 `ListingStatusManager` 支持可替换 reporter；`pytest`: 82 passed |
| TASK-030 | Service 层去展示化：品类判定输出边界 | P1 | ✅ | Codex | 偏移缓解 Phase 4 | 2026-05-07 | 2026-05-04 | `CategoryService` 支持可替换 reporter，`PricingService` 传递同一 reporter；`pytest`: 84 passed |
| TASK-031 | Service 层去展示化：模板管理输出边界 | P1 | ✅ | Codex | 偏移缓解 Phase 4 | 2026-05-07 | 2026-05-04 | `TemplateManagementService` 支持可替换 reporter；`pytest`: 86 passed |
| TASK-032 | 补核心发品服务分支测试 | P1 | ✅ | Codex | 偏移缓解 Phase 5 | 2026-05-07 | 2026-05-04 | `ProductListingService` 覆盖早退、回滚、变体父子行生成路径；`pytest`: 90 passed |
| TASK-033 | 补 SKU 映射服务分支测试 | P1 | ✅ | Codex | 偏移缓解 Phase 5 | 2026-05-07 | 2026-05-04 | `SkuMappingService` 覆盖空源、全已映射、创建、回滚、生成冲突路径；`pytest`: 95 passed |
| TASK-034 | 补变体主题服务 LLM 判定分支测试 | P1 | ✅ | Codex | 偏移缓解 Phase 5 | 2026-05-07 | 2026-05-04 | `VariationThemeService` 覆盖首轮成功、重复纠正、fallback、格式化路径；`pytest`: 101 passed |
| TASK-035 | 补数据映射助手核心规则测试 | P1 | ✅ | Codex | 偏移缓解 Phase 5 | 2026-05-07 | 2026-05-04 | `DataMappingHelper` 覆盖有效值对齐、字段引用、JSONB/尺寸/重量/品类/LLM 路径；`pytest`: 106 passed |
| TASK-036 | 拆分 `DataMappingHelper` 文件规模红线 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | LLM 增强逻辑拆到 `src/utils/data_mapping_llm.py`，`data_mapping_helper.py` 降至 445 行；`pytest`: 106 passed |
| TASK-037 | 更新架构文档以反映 CLI 拆分与输出边界 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | `docs/architecture.md` 已补 `src/cli/*`、`ProgressReporter`、`data_mapping_llm`；`pytest`: 106 passed |
| TASK-038 | 拆分 `ProductListingService` 变体构造职责 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | 变体父子行构造拆到 `ProductListingVariationBuilder`，`product_listing_service.py` 降至 369 行；`pytest`: 106 passed |
| TASK-039 | 拆分模板规则矫正辅助逻辑 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | 报错报告解析和必填规则矫正拆到 `amz_template_rule_correction.py`，模板管理服务降至 389 行；`pytest`: 106 passed |
| TASK-040 | 拆分品类映射 CSV 更新流程 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | CSV 读取、验证、更新流程拆到 `CategoryMappingCsvUpdater`，品类维护服务降至 227 行；`pytest`: 106 passed |
| TASK-041 | 拆分 `DataMappingHelper` 单字段映射职责 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | source type 映射、JSONB、单位换算和重量计算拆到 `DataFieldMapper`，`data_mapping_helper.py` 降至 331 行；覆盖率 55.42%；`pytest`: 106 passed |
| TASK-042 | 拆分模板解析纯规则并补测试 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | 表头识别、字段定义提取、有效值解析拆到 `template_parser_helpers.py`，`amz_template_parser.py` 降至 285 行，parser 覆盖率 71%，总覆盖率 58.40%；`pytest`: 109 passed |
| TASK-043 | 拆分模板变体配置职责 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | 变体字段映射、优先主题输入/历史/default 选择拆到 `template_variation_config.py`，模板管理服务降至 291 行；总覆盖率 58.53%；`pytest`: 114 passed |
| TASK-044 | 拆分核心发品服务配置/结果/日志职责 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | 品类配置加载、待发 SKU 过滤、结果字典、发品日志构造拆出，`product_listing_service.py` 降至 294 行；总覆盖率 58.84%；`pytest`: 118 passed |
| TASK-045 | 拆分变体主题 LLM prompt 准备与属性格式化职责 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | 清洗产品、prompt 组装、优先主题过滤、唯一性校验和属性格式化拆到 `variation_theme_helpers.py`，服务降至 229 行；总覆盖率 58.93%；`pytest`: 121 passed |
| TASK-046 | 拆分数据映射有效值对齐与 LLM 任务提取职责 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | 有效值对齐和 LLM task 提取拆到 `data_mapping_valid_values.py`、`data_mapping_tasks.py`，`data_mapping_helper.py` 降至 261 行；总覆盖率 59.33%；`pytest`: 123 passed |
| TASK-047 | 拆分 Giga 价格仓库数据转换职责 | P1 | ✅ | Codex | 偏移缓解 Phase 6 | 2026-05-07 | 2026-05-04 | 价格过滤、按 Giga 指数去重、base/tier row 构造拆到 `giga_price_transform.py`，价格仓库降至 277 行；总覆盖率 60.60%；`pytest`: 127 passed |
| TASK-048 | 加强核心发品链路集成测试 | P1 | ✅ | Codex | 偏移缓解 Phase 7 | 2026-05-05 | 2026-05-05 | 新增 `tests/integration/services/test_product_listing_generation_flow.py`，覆盖 service/helper/mapper/excel/log 协作链路；`pytest`: 128 passed，覆盖率 60.79% |
| TASK-049 | 加强发品 repository SQL 边界集成测试 | P1 | ✅ | Codex | 偏移缓解 Phase 7 | 2026-05-05 | 2026-05-05 | 新增 `tests/integration/repositories/test_product_listing_repository_sql_contract.py`，固定待发品筛选、变体查询和品类映射 SQL 契约；`pytest`: 134 passed，覆盖率 61.02% |
| TASK-050 | 加强 Giga 商品同步编排集成测试 | P1 | ✅ | Codex | 偏移缓解 Phase 7 | 2026-05-05 | 2026-05-05 | 新增 `tests/integration/services/test_giga_sync_flow.py`，覆盖分页 SKU 获取、详情批处理、提交/回滚和统计输出；`pytest`: 137 passed，覆盖率 61.28% |
| TASK-051 | 加强 Giga 价格同步编排集成测试 | P1 | ✅ | Codex | 偏移缓解 Phase 7 | 2026-05-05 | 2026-05-05 | 新增 `tests/integration/services/test_giga_price_sync_flow.py`，覆盖价格批处理、限流、提交/回滚、重试和统计输出；`pytest`: 140 passed，覆盖率 62.74% |
| TASK-052 | 加强 Giga 库存同步编排集成测试 | P1 | ✅ | Codex | 偏移缓解 Phase 7 | 2026-05-05 | 2026-05-05 | 新增 `tests/integration/services/test_giga_inventory_sync_flow.py`，覆盖库存批次调度、成功/失败批次、限流和统计输出；`pytest`: 142 passed，覆盖率 62.90% |
| TASK-053 | 加强库存价格更新文件生成集成测试 | P1 | ✅ | Codex | 偏移缓解 Phase 7 | 2026-05-05 | 2026-05-05 | 新增 `tests/integration/services/test_inventory_price_update_file_flow.py`，覆盖 SKU/价格/库存整合、TSV 输出列顺序和空值兜底；`pytest`: 143 passed，覆盖率 63.59% |
| TASK-054 | 加强库存价格更新 repository SQL 边界集成测试 | P1 | ✅ | Codex | 偏移缓解 Phase 7 | 2026-05-05 | 2026-05-05 | 新增 `tests/integration/repositories/test_listing_data_repository_sql_contract.py`，覆盖 SKU 映射、价格/库存批量查询、空输入和异常兜底；`pytest`: 149 passed，覆盖率 64.31% |
