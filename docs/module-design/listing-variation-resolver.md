# Listing Variation Resolver

## 目标

API 发品路径在构建 Listings Items payload 前，必须先确定变体家族结构：

- 新变体家族：选择买家可理解、属性可唯一地区分子体的 variation theme。
- 已发布父体增量子体：继承历史父体 theme，只补新 child，禁止创建重复父体。
- 任一决策都要落审计表，能回放输入、候选属性、评分和阻断原因。

## 当前实现

入口：`ProductListingService._build_api_native_plans_for_category()`

核心模块：

- `AmazonVariationResolver`：只负责 theme 选择、child attribute 提取、唯一性校验。
- `AmazonVariationResolutionRepository`：写入 `amazon_variation_resolution_runs`。
- `ProductListingRepository.get_meow_skus_by_vendor_skus()`：把 Giga 关联 SKU 映射回 meowy SKU。
- `AmzListingLogRepository.find_log_for_family()` / `get_family_details_by_parent()`：查历史父体和已有子体属性。

## 新家族策略

配置文件：`config/listing_gates/variation_theme_strategy.yaml`

当前 CABINET 支持：

- `Color`
- `Size`
- `Color/Size`

resolver 会为每个 theme 计算：

- `uniqueness`：所有 child 的属性组合必须唯一。
- `buyer_relevance`：按品类配置体现买家浏览和购买决策优先级。
- `data_confidence`：属性来源是否完整。
- `simplicity`：能用单属性区分时不优先使用组合 theme。
- `coverage`：所有 child 都必须有 required attributes。

只有唯一、完整、分数达到 `minimum_auto_pass_score` 的 theme 才会自动通过。

## 增量子体策略

当待发 SKU 的 `raw_data.associateProductList` 指向已有 Giga 家族成员时：

1. 映射关联 Giga SKU 到 meowy SKU。
2. 查询这些 meowy SKU 的发品日志。
3. 如存在有效 `parent_sku` + `variation_theme`，继承该父体。
4. 按历史 theme 抽取新 SKU 的 child attributes。
5. 与同父体已有 child 的属性组合做唯一性校验。

重复或缺失 required attributes 时，返回 `blocked_variation_resolution`，不生成 payload。

## 设计边界

- resolver 不调用 Amazon API，不构建 payload，不写发品日志。
- payload builder 只消费 resolver 给出的 `ListingVariation`。
- 当前是 deterministic-first MVP，没有接 LLM 自动选择 theme。
- 后续可在 resolver 内新增 LLM 候选生成，但仍必须经过唯一性、完整性、审计落库后才能放行。

## 审计表

表：`amazon_variation_resolution_runs`

关键字段：

- `mode`：`new_family` / `append_child`
- `parent_sku`
- `product_type`
- `selected_theme`
- `decision`
- `child_skus`
- `candidate_snapshot`
- `score_snapshot`
- `existing_family_snapshot`
- `finding_snapshot`
- `resolver_version`

## 未完成空间

- 扩展非 CABINET 品类的 theme 配置和属性来源。
- 将 Amazon Product Type Definitions 的 variation theme 与属性要求纳入缓存校验。
- 增加人工复核队列：低置信度、无合格 theme、重复属性但疑似数据错误的场景进入 human-in-loop。
