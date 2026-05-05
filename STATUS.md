# Project Status

## 当前阶段
- **阶段**：偏移缓解 Phase 7 持续推进
- **里程碑**：测试/CI基线、关键模块文档、入口层拆分、主要 service 输出边界、重点大文件职责拆分、核心链路集成测试持续收敛

## 最新进展
- ✅ **2026-05-04 / Codex**: 修复库存同步单测挂起问题，完整测试从卡住恢复为 `52 passed in 1.34s`。
- ✅ **2026-05-04 / Codex**: 调整 `.gitignore`，不再屏蔽 `tests/` 下的正式 `test_*.py` 单测文件。
- ✅ **2026-05-04 / Codex**: 建立覆盖率基线：当前 `127 passed in 9.12s`，总覆盖率 `60.60%`。
- ✅ **2026-05-04 / Codex**: 已新增 `.github/workflows/ci.yml` 并接入 repo-level runner `amz-listing-runner-01`；CI run `25330003050` 在 commit `c5dc219` 绿色通过。
- ✅ **2026-05-04 / Codex**: 补齐关键模块设计文档和 service 返回契约草案，覆盖发品、Giga同步、价格库存、模板映射。
- ⏳ **2026-05-04 / Codex**: 开始拆分 `main.py` 前置收敛，已将重复的非交互任务分发逻辑合并到 `_dispatch_task()`；`pytest` 仍为 52 passed。
- ⏳ **2026-05-04 / Codex**: 修复无 `--task` 时交互菜单不可达的问题，并将交互菜单壳拆到 `src/cli/menu.py`；`main.py` 从 937 行降至 843 行。
- ⏳ **2026-05-04 / Codex**: 将任务分发改为注册表形式，并为 `src/cli/menu.py` 补 3 个单测；`pytest` 当前 55 passed，覆盖率 39%。
- ⏳ **2026-05-04 / Codex**: 将只读查询 handler 拆到 `src/cli/query_handlers.py`，并补 3 个单测；`main.py` 当前 673 行。
- ⏳ **2026-05-04 / Codex**: 将类目配置 handler 拆到 `src/cli/category_handlers.py`，并补 4 个单测；`main.py` 当前 445 行，低于 500 行红线。
- ⏳ **2026-05-04 / Codex**: 将发品生成 handler 拆到 `src/cli/listing_handlers.py`，并补 2 个单测；`main.py` 当前 378 行。
- ✅ **2026-05-04 / Codex**: 将运营 handler 拆到 `src/cli/operation_handlers.py`，任务注册拆到 `src/cli/task_dispatcher.py`；`main.py` 当前 96 行，已低于 150 行目标。
- ✅ **2026-05-04 / Codex**: 完成 Phase 4 主要输出边界收敛，`PricingService`、`GigaSyncService`、`GigaInventorySyncService`、`GigaPriceSyncService` 均支持可替换 progress reporter，默认 CLI 输出保持不变，并补静默 reporter 单测。
- ✅ **2026-05-04 / Codex**: 继续收敛更新文件编排服务，`InventoryPriceUpdaterService` 支持可替换 progress reporter，并将同一 reporter 传递给价格、库存、售价子服务。
- ✅ **2026-05-04 / Codex**: 继续收敛 AI 商品详情生成服务，`ProductDetailGenerationService` 支持可替换 progress reporter，默认 CLI 输出保持不变，并补无 SKU/分批处理静默单测。
- ✅ **2026-05-04 / Codex**: 继续收敛品类维护服务，`CategoryMaintenanceService` 支持可替换 progress reporter，默认 CLI 输出保持不变，并补同步/CSV 静默单测。
- ✅ **2026-05-04 / Codex**: 将 `PricingService` 的本地 reporter 类收敛为统一 `progress_reporter.py` 的兼容子类，保留原导出类名。
- ✅ **2026-05-04 / Codex**: 继续收敛全量报告导入与发品状态更新服务，`AmzFullListImporterService`、`ListingStatusManager` 支持可替换 progress reporter，并补事务/静默单测。
- ✅ **2026-05-04 / Codex**: 继续收敛品类判定服务，`CategoryService` 支持可替换 progress reporter，`PricingService` 会传递同一 reporter 到品类判定链路。
- ✅ **2026-05-04 / Codex**: 继续收敛模板管理服务，`TemplateManagementService` 支持可替换 progress reporter；`input` 提示改为 reporter 输出后再读取输入，默认交互能力保留。
- ✅ **2026-05-04 / Codex**: 补充核心发品服务分支测试，覆盖品类无 SKU、缺模板、Excel 生成异常回滚、变体父子行与日志生成路径；`ProductListingService` 覆盖率提升至 80%。
- ✅ **2026-05-04 / Codex**: 补充 SKU 映射服务分支测试，覆盖空源、全已映射、创建新映射、插入异常回滚、SKU 生成冲突重试失败路径；`SkuMappingService` 覆盖率提升至 93%。
- ✅ **2026-05-04 / Codex**: 补充变体主题服务 LLM 判定测试，覆盖首轮成功、重复属性二轮纠正、缺 prompt fallback、LLM 异常 fallback、尺寸格式化和 HTML 清洗；`VariationThemeService` 覆盖率提升至 93%。
- ✅ **2026-05-04 / Codex**: 补充数据映射助手核心规则测试，覆盖有效值对齐、字段引用、JSONB fallback、数组/组合计算、尺寸/重量/品类查找、LLM 增强与 fallback；`DataMappingHelper` 覆盖率提升至 77%。
- ✅ **2026-05-04 / Codex**: 拆分 `DataMappingHelper` 文件规模红线，将 LLM 增强逻辑迁移到 `src/utils/data_mapping_llm.py`，原 helper 保留兼容委托方法并降至 445 行。
- ✅ **2026-05-04 / Codex**: 更新架构文档，补齐当前 `src/cli/*` 分层、`ProgressReporter` 输出边界和 `data_mapping_llm` 映射增强模块。
- ✅ **2026-05-04 / Codex**: 拆分 `ProductListingService` 变体构造职责，将父子行和变体日志构造迁移到 `ProductListingVariationBuilder`，原 service 降至 369 行。
- ✅ **2026-05-04 / Codex**: 拆分模板规则矫正辅助逻辑，将 Amazon 报错报告解析和必填规则矫正迁移到 `amz_template_rule_correction.py`，模板管理服务降至 389 行。
- ✅ **2026-05-04 / Codex**: 拆分品类映射 CSV 更新流程，将文件读取、行验证、批量更新和输出统计迁移到 `CategoryMappingCsvUpdater`，品类维护服务降至 227 行。
- ✅ **2026-05-04 / Codex**: 拆分 `DataMappingHelper` 单字段映射职责，将 source type 映射、JSONB 读取、单位换算和重量计算迁移到 `DataFieldMapper`，原 helper 降至 331 行；覆盖率 `55.42%`。
- ✅ **2026-05-04 / Codex**: 拆分模板解析纯规则，将 Data Definitions 表头/字段提取、Valid Values 解析迁移到 `template_parser_helpers.py`，`amz_template_parser.py` 降至 285 行；parser 覆盖率提升至 71%，总覆盖率 `58.40%`。
- ✅ **2026-05-04 / Codex**: 拆分模板变体配置职责，将变体字段映射、优先主题用户输入/历史/default 选择迁移到 `template_variation_config.py`，模板管理服务降至 291 行；总覆盖率 `58.53%`。
- ✅ **2026-05-04 / Codex**: 拆分核心发品服务配置/结果/日志职责，将品类配置加载、待发 SKU 过滤、结果字典和日志 payload 构造迁移到独立 helper，`product_listing_service.py` 降至 294 行；总覆盖率 `58.84%`。
- ✅ **2026-05-04 / Codex**: 拆分变体主题 LLM prompt 准备与属性格式化职责，将产品清洗、prompt 组装、优先主题过滤、唯一性校验和格式化迁移到 `variation_theme_helpers.py`，服务降至 229 行；总覆盖率 `58.93%`。
- ✅ **2026-05-04 / Codex**: 拆分数据映射有效值对齐与 LLM task 提取职责，将有效值对齐、模糊匹配和 LLM 任务提取迁移到 `data_mapping_valid_values.py` / `data_mapping_tasks.py`，`data_mapping_helper.py` 降至 261 行；总覆盖率 `59.33%`。
- ✅ **2026-05-04 / Codex**: 拆分 Giga 价格仓库数据转换职责，将无效价格过滤、按 Giga 指数去重、base/tier row 构造迁移到 `giga_price_transform.py`，`giga_product_price_repository.py` 降至 277 行；总覆盖率 `60.60%`。
- ✅ **2026-05-05 / Codex**: 新增核心发品链路集成测试，覆盖 `ProductListingService` 与变体识别、字段映射、Excel 生成、发品日志构造、事务提交的协作路径；`pytest` 当前 128 passed，总覆盖率 `60.79%`。
- ✅ **TASK-012**: 完成 `pydantic-settings` 迁移，重构了 `main.py`, `db_pool.py`, `logging`, `llm`, `giga` 等模块。
- ✅ **TASK-011**: 配置了 Pre-commit Hooks。
- ✅ **TASK-010**: 完成 Alembic 数据库迁移工具配置。

## 下一步计划
- 🔲 继续补集成测试，优先覆盖 repository SQL 边界、Giga 同步编排和更新文件生成路径。
- ✅ 当前已消除本轮识别出的 300+ 行文件规模预警。

## 风险与阻塞
- 当前覆盖率 `60.79%`，仍低于开发规范对核心业务逻辑的目标。
- GitHub Actions self-hosted runner 已注册并 online；CI run `25330003050` 已在 `amz-listing-runner-01` 绿色通过。GitHub 提示 `actions/checkout@v4` 当前 Node.js 20 runtime 将在 2026-06-02 默认切到 Node.js 24，需要后续跟踪。
- service 层直接 stdout 已基本收敛到统一 reporter；`amz_template_parser.py` 的 `_log_and_print` 仅写 logger，名称命中 `rg "print\\("` 但不输出 stdout。
- `main.py` 已降至 96 行，入口层拆分目标已完成；业务 service 和 repository 侧本轮识别出的 300+ 行文件规模预警已全部消除。
- 生产部署配置仍未按服务器运维规范接入 `/data/docker-compose/` 与共享 PostgreSQL。
