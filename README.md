# Amazon Listing Management System

亚马逊商品全生命周期运营管理系统 — 覆盖选品→上架→成长→成熟→衰退的完整自动化运营平台

---

## 🚀 快速开始

> **项目状态**：[查看进度 (STATUS.md)](./STATUS.md) | [待办任务 (TODO.md)](./TODO.md)

### 当前生产状态

- 生产镜像：`amz-listing-management-system:2026-06-15`
- 生产入口：`https://amz-listing.meowy.fans`（SSO ForwardAuth）
- 新品发品主路径：`generate-listing-api`，默认 dry-run
- Excel 新品发品：deprecated；`generate-listing` 仅作为 API-native dry-run 兼容入口
- 最新部署验收：`docs/test-reports/2026-06-15-api-native-quality-production-deploy.md`

### 基础命令
```bash
# 交互式菜单
python3 main.py

# 非交互式任务
python3 main.py --task <task-name> [--category CATEGORY] [--auto-confirm] [--no-dry-run] [--strict-validation] [--sku SKU] [--sku-file FILE] [--only-not-on-amazon]
```

### 可用任务（40 个）

**Giga 商品管理**：`sync-products`, `import-amz-report`, `sync-amz-report-api`, `update-listing-status`, `generate-details`, `sync-prices`, `sync-inventory`, `update-prices`

**数据查询**：`view-statistics`, `pending-statistics`, `recent-listings`, `list-categories`

**类目配置**：`discover-product-type`, `suggest-category-mappings`, `sync-giga-categories`, `update-mappings-from-csv`, `sku-sync-from-csv`

> `template-update` / `template-correction` 属于 Excel 模板时代的 legacy 工具，仅用于历史模板迁移或排障，不再作为类目接入主路径。

**Listing 发品**：`generate-listing-api`（API-native 唯一新品发品入口）, `generate-update-file`, `update-price-inventory-api`

> `generate-listing` / Excel 新品发品流程已 deprecated。历史 Excel 解析、模板和文件生成模块仅保留为迁移参考与旧数据兼容，不再作为运营入口。
> `generate-listing-api --strict-validation` 会在 dry-run 下调用 Amazon `VALIDATION_PREVIEW` 做权威预检并持久化 issues；默认 dry-run 仍为离线预览，不访问 Amazon 写接口。
> `--sku` / `--sku-file` 可限制本次发品候选集；`--only-not-on-amazon` 会先只读查询 Amazon 并跳过已存在 SKU。

**运营监控**：`sync-listing-issues`

**🆕 关键词与竞品**：`keyword-research`, `competitive-analysis`

**🆕 巡检与报告**：`daily-check`, `weekly-report`

**🆕 利润与库存**：`profit-analysis`, `inventory-health`, `lifecycle-summary`

**🆕 Amazon 订单（Phase A）**：`sync-amazon-orders`, `amazon-order-daily-report`, `test-feishu-alert`

---

## 📋 系统架构

```
项目结构
├── main.py                          # 主程序入口（96 行）
├── infrastructure/                  # 基础设施层
│   ├── db_pool.py                  # 数据库连接池
│   ├── exceptions.py               # AppException, ValidationException
│   ├── validators.py               # 输入校验
│   ├── logging_config.py           # 日志配置
│   ├── feishu_client.py            # 🆕 飞书 Webhook 推送
│   ├── amazon/                     # Amazon SP-API 客户端
│   │   ├── config.py              # AmazonConfig
│   │   ├── token_manager.py        # LWA OAuth2 令牌管理
│   │   ├── api_client.py          # SP-API HTTP 客户端（重试/代理）
│   │   ├── listings_client.py     # Listings Items API
│   │   ├── reports_client.py      # Reports API
│   │   ├── orders_client.py       # 🆕 Orders API（Phase A 只读拉单）
│   │   ├── product_type_client.py # Product Type Definitions API
│   │   ├── pricing_client.py      # 🆕 Product Pricing API
│   │   ├── catalog_client.py      # 🆕 Catalog Items API
│   │   ├── ads_client.py          # 🆕 Amazon Ads API
│   │   └── brand_analytics_client.py # 🆕 Brand Analytics SQP API
│   ├── giga/                       # GigaCloud 供应商 API
│   └── llm/                        # LLM 集成（DeepSeek/Qwen/AutoGen）
├── src/
│   ├── cli/                        # CLI 展现层
│   │   ├── menu.py                # 交互式菜单
│   │   ├── task_dispatcher.py     # 任务注册与分发（40 个任务）
│   │   ├── listing_handlers.py    # 发品 handler
│   │   ├── operation_handlers.py  # 运营 + 🆕 Phase 1-3 handler
│   │   ├── category_handlers.py   # 类目配置 handler
│   │   └── query_handlers.py      # 查询 handler
│   ├── config/
│   │   └── settings.py            # Pydantic Settings
│   ├── models/
│   │   └── product.py             # StandardProduct（供应商无关）
│   ├── repositories/               # 16 个数据仓库
│   ├── services/                   # 业务服务层（37 个模块）
│   │   ├── product_lifecycle_service.py     # 🆕 商品生命周期状态机
│   │   ├── keyword_research_service.py      # 🆕 LLM 关键词研究+分层
│   │   ├── competitive_intel_service.py     # 🆕 竞品情报分析
│   │   ├── keyword_ranking_tracker.py       # 🆕 关键词排名追踪
│   │   ├── review_sentiment_analyzer.py     # 🆕 评论情感分析
│   │   ├── ppc_management_service.py        # 🆕 广告 Campaign 管理
│   │   ├── profit_analyzer.py               # 🆕 单品利润核算
│   │   ├── inventory_planner.py             # 🆕 库存健康+补货计划
│   │   ├── content_performance_analyzer.py   # 🆕 A+ 内容效果分析
│   │   ├── daily_check_service.py           # 🆕 每日巡检编排
│   │   ├── amazon_order_sync_service.py     # 🆕 Amazon 订单轮询+飞书通知
│   │   ├── amazon_order_daily_report_service.py # 🆕 订单 24h 健康日报
│   │   ├── weekly_report_service.py         # 🆕 每周运营报告
│   │   ├── product_content_generator.py     # 品类感知 LLM 内容生成
│   │   ├── amazon_listing_quality_gate.py   # 发品前质量闸门
│   │   ├── amazon_listing_issue_sync_service.py  # Issue 同步+修复
│   │   └── ... (原有 service 模块)
│   └── utils/                     # 工具层
├── config/                        # 静态配置
│   ├── amz_listing_data_mapping/  # 字段映射 JSON
│   ├── pricing/                   # 定价策略 YAML
│   └── api_clients/               # 🆕 LLM Prompt 模板（8 个场景）
├── migrations/                    # SQL 迁移（12 张新表）
├── template_files/                # Deprecated Excel 模板归档
├── output/                        # 输出目录
├── docs/                          # 设计文档
└── tests/                         # 测试（500+ tests）
```

---

## 🔄 商品全生命周期

```
选品期 → 准备期 → 上线期 → 成长期 → 成熟期 → 衰退期
  │        │        │        │        │        │
  │        │        │        │        │        └── 清货Coupon / 替代品推荐
  │        │        │        │        └── 提价测试 / 变体拓展 / 竞品防御
  │        │        │        └── 关键词收割 / ACOS 优化 / 评论分析
  │        │        └── SP-API 提交 / 初始广告 / Vine
  │        └── 关键词研究 / LLM 内容 / COSMO 属性 / 定价
  └── 竞品初筛 / 毛利预估 / 卖家密度 / BSR 信号
```

---

## 📦 依赖要求

```toml
[project]
dependencies = [
    "sqlalchemy>=2.0.23",
    "psycopg2-binary>=2.9.9",
    "pandas>=2.1.3",
    "python-dotenv>=1.0.0",
    "openpyxl>=3.1.2",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "requests>=2.31",
    "pyyaml>=6.0",
]
```

---

## 🧪 运行测试

```bash
python3 -m pytest tests/ -q    # 全部测试
python3 -m pytest tests/ -x -q # 遇到第一个失败停止
```

## 🚢 生产部署

```bash
/home/liangqinhao/amz_listing_management_system/deploy/production/deploy.sh
```

部署契约与 smoke 命令见 `deploy/production/README.md`。生产 compose 源文件在 `deploy/production/docker-compose.yml`，上线时需同步到 `/data/docker-compose/amz-listing-management-system/docker-compose.yml` 并同步 `/data/README.md`、`/data/TODO.md` 服务登记。

---

## 🔧 环境变量

```bash
# 数据库
DATABASE_HOST=localhost DATABASE_PORT=5432 DATABASE_NAME=amz_listing
DATABASE_USER=postgres DATABASE_PASSWORD=xxx

# GigaCloud API
GIGA_BASE_URL=https://api.gigacloudlogistics.com
GIGA_CLIENT_ID=xxx GIGA_CLIENT_SECRET=xxx

# Amazon SP-API
AMAZON_LWA_CLIENT_ID=xxx AMAZON_LWA_CLIENT_SECRET=xxx
AMAZON_REFRESH_TOKEN=xxx AMAZON_SELLER_ID=xxx
AMAZON_MARKETPLACE_ID=ATVPDKIKX0DER

# LLM
LLM_PROVIDER=deepseek DEEPSEEK_API_KEY=xxx

# 飞书推送
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx

# Amazon 订单同步（Phase A）
AMAZON_ORDER_SYNC_NOTIFY=true
AMAZON_ORDER_SYNC_LOOKBACK_HOURS=48
AMAZON_ORDER_SYNC_INTERVAL_SECONDS=1800
AMAZON_ORDER_SYNC_FAILURE_ALERT_THRESHOLD=3
AMAZON_ORDER_DAILY_REPORT_NOTIFY=true
AMAZON_ORDER_DAILY_REPORT_HOURS=24
AMAZON_ORDER_DAILY_REPORT_HOUR=9
AMAZON_ORDER_DAILY_REPORT_TZ=Asia/Shanghai

# 可选
LISTING_ISSUE_SCHEDULER_ENABLED=true
AMAZON_ADS_PROFILE_ID=xxx
```
