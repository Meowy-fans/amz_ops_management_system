# 需求：新品类自动判定亚马逊 Product Type 并完成映射

## 背景

当前发品系统依赖 `supplier_categories_map` 表将 Giga 品类映射到 Amazon product type。映射存在才能发品。

现状：348 个 Giga 收藏商品中，85 个（24%）因缺少品类映射而无法发品，涉及 27 个 Giga 品类（Sofas、Vanities、Chairs 等）。

当前人工流程：
1. `suggest-category-mappings` — 对品类用产品名关键词搜 Amazon product type，列出候选（一次只处理 3 个品类）
2. `discover-product-type` — 人工输入关键词，逐个探索 product type 并手动确认映射
3. 完全依赖人工，无法规模化

## 目标

新品发品时，**无需人工介入**，系统自动完成：

1. 根据产品信息判定 Amazon product type
2. 将 Giga 品类 → Amazon product type 的映射写入 `supplier_categories_map`
3. 缓存 product type schema
4. 后续同品类商品直接复用映射发品

## 调研发现

### Amazon SP-API 可用能力

#### 方案 A：Product Type Definitions `searchDefinitions`
- **端点**: `GET /definitions/2020-09-01/productTypes?keywords=...&marketplaceIds=...`
- **已有客户端**: `AmazonProductTypeClient.search_product_types(keywords)` — `infrastructure/amazon/product_type_client.py`
- **行为**: 输入关键词字符串，返回匹配的 product type 名称列表
- **当前代码**: `suggest-category-mappings` handler（`src/cli/operation_handlers.py:429`）已在用，但用产品名前 5 词做关键词太粗糙，且只列候选不自动选择
- **自动化路径**: LLM 提取关键词 → 调 API → 自动从候选中选最佳
- **缺点**: 依赖关键词质量；Amazon product type 命名不直观，LLM 可能选错

#### 方案 B：Catalog Items API 反向查找（推荐）
- **端点 1**: `GET /catalog/2022-04-01/items?keywords=...&marketplaceIds=...`
- **端点 2**: `GET /catalog/2022-04-01/items/{asin}?includedData=summaries`
- **已有客户端**: `CatalogClient` — `infrastructure/amazon/catalog_client.py`
  - `search_catalog_items(keywords)` — 搜 Amazon 全量目录，返回匹配 ASIN 列表
  - `get_summary(asin)` — 返回单个 ASIN 摘要，**包含 `productType` 字段**
  - `batch_get_summaries(asins)` — 批量（每批 20），也提取 `productType`
- **行为**: 用产品关键词搜同类 ASIN → 查出这些 ASIN 的 product type → 投票
- **优势**: 直接用 Amazon 自己的分类结果，不依赖 product type 命名规则理解；数据已在 Catalog API 返回中（`itemClassification` 字段）

#### 方案 C：已有卖家 listing 的 product type
- `ListingsClient.search_listings_items()` + `get_listings_item()` 只能查**自己卖家**的 listing
- 对新品类无用（没有自家 listing 可以参考）

### 代码库现有轮子

| 能力 | 文件 | 方法 | 状态 |
|------|------|------|------|
| 关键词 → product type 名称 | `product_type_client.py` | `search_product_types()` | 已有，人工用 |
| 关键词 → 同类 ASIN | `catalog_client.py` | `search_catalog_items()` | 已有，竞品分析用 |
| ASIN → product type | `catalog_client.py` | `get_summary()` / `batch_get_summaries()` | 已有，已提取 `productType` |
| Schema 下载 + 缓存 | `schema_service.py` | `fetch_and_cache()` | 已有，发品时自动 |
| 映射表读写 | `amazon_product_type_schema_repository.py` | upsert | 已有 |
| supplier_categories_map 写入 | `src/cli/operation_handlers.py:347` | `handle_discover_product_type` | 已有写表逻辑 |

**缺少的只是一段串联逻辑**：产品数据 → 提取关键词 → 搜 Catalog → 拿 ASIN → 取 product type → 投票 → 写入映射。

## 实现要求

### 核心流程

```
输入: Giga supplier_category_code (如 "10027")
      ↓
1. 从该品类取 3-5 个代表性产品名（已有，giga_product_sync_records.raw_data->>'name'）
      ↓
2. 对每个产品提取关键词（取前 3-5 个有意义的词）
      ↓
3. 调用 CatalogClient.search_catalog_items(keywords)
   → 获得同类 ASIN 列表（取前 5-10 个）
      ↓
4. 调用 CatalogClient.batch_get_summaries(asins)
   → 每个 ASIN 的 productType（在 summaries[].productType / itemClassification 中）
      ↓
5. 投票：出现最多的 product type 作为最终选择
      ↓
6. 写入 supplier_categories_map：
   - supplier_category_code = 输入品类
   - supplier_platform = 'giga'
   - standard_category_name = 投票结果
      ↓
7. 调用 AmazonSchemaService.fetch_and_cache(product_type) 预缓存 schema
```

### 新增 CLI task

任务名：`auto-map-category` 或 `auto-discover-category`

参数：
- `--category` 或 `--category-code`（Giga 品类代码）
- `--all-unmapped`（一键处理所有未映射品类）
- `--dry-run`（默认 true，只显示候选不写入）

### 涉及文件

**新增/修改**：
- `src/cli/operation_handlers.py` — 新增 handler 函数
- `src/cli/task_dispatcher.py` — 注册新 task
- 可选：`src/services/auto_category_mapper.py` — 如果逻辑复杂可抽 service

**只读复用**：
- `infrastructure/amazon/catalog_client.py` — `search_catalog_items()` + `batch_get_summaries()`
- `infrastructure/amazon/product_type_client.py` — `search_product_types()` 作为 fallback
- `src/services/amazon_schema_service.py` — `fetch_and_cache()`

**写入目标**：
- `supplier_categories_map` 表
- `amazon_product_type_schemas` 表（由 schema_service 自动管理）

### 容错设计

- 单个产品名搜不到 ASIN → 换同品类下一个产品名
- 所有产品名都搜不到 → 降级到方案 A（`search_product_types` 关键词匹配）
- 搜索结果 product type 分散（无多数）→ 标记需要人工审核，不强制映射
- Schema 下载失败 → 记录但完成映射（发品时会自动重试）

### 验收标准

```bash
# 对单个品类自动判定
docker exec amz-listing-management-system python main.py \
  --task auto-discover-category --category-code 10027

# 预期输出: 搜索关键词 → 候选 ASIN → 每个 ASIN 的 product type → 投票结果 → 已写入映射

# 批量处理所有未映射品类
docker exec amz-listing-management-system python main.py \
  --task auto-discover-category --all-unmapped --no-dry-run

# 验证: pending-statistics 中 UNMAPPED 数量应显著减少
docker exec amz-listing-management-system python main.py --task pending-statistics
```
