# 技术方案提案 (Proposal)：亚马逊发品多品类自动化扩展与校验闭环 (Approved Version)

- **状态**：`Approved` (已批准)
- **关联 Epic**：`EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES`
- **设计作者**：Antigravity
- **最后更新**：2026-06-22

---

## 1. 背景与目标 (Background & Objective)

### 1.1 现状背景
在 Amazon Listing Management System 中，目前 Giga 收藏夹选品存在 **85 个缺失品类配置的商品**。其中包括：
1.  **SOFA (19 个)**：在本地 `supplier_categories_map` 中已具备大类映射，但缺少对应的属性解析 YAML 规则。
2.  **UNMAPPED (66 个)**：如化妆台 (Makeup Vanities)、餐椅 (Dining Seating) 等，在本地完全无映射关系。

这 19 个 SOFA 商品将作为本技术提案的首批全链路验证目标。

### 1.2 核心目标
本方案旨在基于现有的 **Schema 驱动属性解析管道 (Schema-Driven Attribute Resolution Pipeline)**，复用及激活已有能力，开发核心缺口模块，最终实现：
1.  **复用已有映射发现能力**：通过已实现的 `AutoCategoryMapper`，零人工干预完成 66 个 `UNMAPPED` 商品的类目投票与 Schema 缓存。
2.  **开发骨架规则生成器**：自动产出 80% 属性 YAML 规则，减少 85+ 品类的人工配置负担。
3.  **新建 yaml.mode 风控校验机制**：在配置解析与发品提交处新建 YAML 运行模式的拦截，保障未经人工审核的规则不会直接提交到 LIVE 环境。
4.  **激活并端到端测试 LLM 提取**：启用已实现的 `LLMAttributeExtractor`，防止大模型发生“属性编造”。
5.  **实态变体防重校验**：在提交前拉取 Amazon 线上已存在变体拓扑，拦截子体属性冲突，将 `DUPLICATE_VARIATION_ATTRIBUTES` 接口错误率降为 0。

---

## 2. 架构设计与核心模块 (Architectural Design)

本设计将开发阶段（生成 YAML）与运行阶段（发品）进行了分离，同时纠正了变体解析与属性提取的先后关系。

### 2.1 整体数据流图

#### A. 配置与生成阶段 (串行)
```
┌─────────────────┐     auto-discover-category     ┌────────────────────────┐
│  Giga 选品采样  ├───────────────────────────────>│ 自动写入 map & 缓存 Schema│
└─────────────────┘                                └───────────┬────────────┘
                                                               │
                                                               ▼ rules-generator (新)
                                                   ┌────────────────────────┐
                                                   │   自动生成 YAML 骨架    │
                                                   │ (mode: dry_run 默认标记)│
                                                   └───────────┬────────────┘
                                                               │
                                                               ▼ (人工微调/解除 dry_run)
                                                   ┌────────────────────────┐
                                                   │  category_rules.yaml   │
                                                   │ (mode: live_eligible)  │
                                                   └────────────────────────┘
```

#### B. 发品运行阶段 (并行)
```
                          ┌────────────────────────┐
                          │     generate-listing   │
                          └───────────┬────────────┘
                                      │
                                      ▼
                      1. AmazonVariationResolver (变体识别)
                                      │ (确定 Theme/在线拓扑/ASIN 反查)
                                      ▼
                      2. AmazonListingPayloadBuilder (属性提取)
                                      │ (通过 YAML 解析 & 激活 LLM 提取)
                                      ▼
                      3. Submitter.submit() -> SP-API
                                      │ (拦截模式: dry_run)
                                      ▼
                                  SP-API PUT
```

---

### 2.2 模块 A：规则生成器 与 yaml.mode 校验机制 —— 新增

#### 2.2.1 规则生成器 (Auto-Attribute Rules Generator)
*   **定位**：品类规则骨架生成器。自动产出 80% 的属性映射配置，剩下的 20% 敏感或定制配置标注为 `# TODO` 留待人工审查。
*   **无法推导需人工补全的项**：
    *   `dimension_strategy` 与 `additional_dimension_measures`（需结合类目尺寸特征手工配置）。
    *   `post_processors`（如 CABINET 专属的 normalizer 处理器）。
    *   `coverage_ignore_when_parent`（父体需忽略 of 子体属性）。
    *   嵌套对象类型中的 `sources` 路径映射（如 `frame[].material` 需核对来源）。
    *   `default` 数据源中的 `evidence` 默认占位字符串。

#### 2.2.2 新增 yaml.mode 拦截机制 (已确定作为 Phase 1 新建功能)
*   **配置层解析**：`AttributeRuleLoader.load()` 扩展对 YAML 根节点 `mode` 字段的提取解析。支持 `dry_run`（默认值）和 `live_eligible` 两个值。
*   **Submitter 门控拦截**：在 `AmazonListingSubmitter` 真实提交 (即 `dry_run=False` 且 `validation_only=False`) 前，获取当前类目解析规则的 `mode` 字段：
    *   如果为 `dry_run`，提交被安全拒绝，返回 `blocked_by_rule_mode` 阻断，并不外呼 Amazon 写入接口。
    *   如果为 `live_eligible`，则允许进行正常的 SP-API 提交。
*   **配套产出**：完成该机制后，需补充 `AttributeRuleLoader` 与 `AmazonListingSubmitter` 对应的单元测试以确保覆盖。

---

### 3. 证据链驱动的 LLM 属性提取器 —— 激活与验证
*   **定位**：激活系统已完整实现但从未使用的 `LLMAttributeExtractor` 模块。
*   **实际增量工作**：
    1.  **YAML 扩展**：在 `sofa.yaml` 等新生成规则中，为需大模型抽取的属性（如沙发的 `back_style`, `arm_style`）配置 `source: llm` 类型。
    2.  **契约测试**：针对 `value`, `evidence`, `confidence` 三元组进行端到端测试，验证大模型无法在文本中找到证据时返回 null 或被 `needs_manual_review` 门控拦截的有效性。
    3.  **Prompt 调优**：在 `api_clients/` 调优 `product_content_review` 词条以提升敏感属性抽取召回率。
    4.  **回归回归**：确保已接入品类（CABINET, OTTOMAN, HOME_MIRROR）完全不受影响。

---

## 4. 变体父子拓扑校验器 (Variation Hierarchy Audit Gate) —— 新增

### 4.1 在线查重反查链路细节
对于 `resolve_append_child` 路径，系统在没有 Parent 属性直接映射时，通过以下链路执行 ASIN 反解及同胞子体属性获取：

```
待发子体 meow_sku
       │
       ▼ [1. 反查 ASIN]
本地 meow_sku_map + amz_all_listing_report -> 找不到 -> 调用 get_listings_item(parent_sku)
       │
       ▼ [2. 获取 Parent ASIN]
    得到 parent_asin (如 B0XXXXXXX)
       │
       ▼ [3. 获取同胞 ASIN 列表]
调用 getCatalogItem(parent_asin, includedData=["variations"])
       │
       ▼ [4. 提取 variations 关系树]
从响应中获取同胞 ASIN/SKU 关系列表
       │
       ▼ [5. 提取实态属性值]
批次/并发调用 get_listings_item(sku) -> 提取 color/size 值 -> 组装在线实态变体矩阵
```

### 4.2 依赖注入与限速设计
*   **依赖澄清**：目前 `catalog_client` 尚未注入 `ProductListingAPIPlanBuilder` 或者是 `AmazonVariationResolver`。在 Phase 3 实施时，需要在 `AmazonVariationResolver` 类的 `__init__` 中新增并引入 `catalog_client` 依赖项。
*   **限速管理**：
    *   Amazon Listings Items API 查询限制为 **5 req/sec**，每次请求延迟约 **300ms - 500ms**。
    *   **解决方案**：步骤 3 强制指定 `includedData=["variations"]`，通过单次 `getCatalogItem` 调用获取完整的变体子体 SKU 拓扑，避免因多次调用造成的 429 API 超速限流。对步骤 5 提取具体属性值时应用并发线程限速防御，防止并发请求数超限。

---

## 5. 接口契约与数据模型 (API Contracts & Models)

### 5.1 变体冲突日志表设计 (`amazon_variation_conflict_logs`)
新增外键关联和阻断列表字段设计，升级如下：

```sql
CREATE TABLE amazon_variation_conflict_logs (
    id SERIAL PRIMARY KEY,
    resolution_run_id INTEGER REFERENCES amazon_variation_resolution_runs(id) ON DELETE CASCADE,
    parent_sku VARCHAR(255) NOT NULL,
    variation_theme VARCHAR(50) NOT NULL,
    conflicting_attributes JSONB NOT NULL, -- 冲突的属性组合, 如 {"color": "Blue"}
    blocked_skus JSONB NOT NULL,           -- 被阻断的候选子体 SKU 列表
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE   -- 冲突实际解决的时间戳
);
```

---

## 6. 实施规划路径 (Implementation Path)

由于主要代码块已具备良好基础，工期和 Phase 阶段重调为实际的增量交付：

| 阶段 | 核心任务 | 交付物 | 评审边界 |
| :---: | :--- | :--- | :--- |
| **Phase 1** | 1. 实现 rules-generator CLI 工具。<br>2. 升级 `AttributeRuleLoader` 支持 `mode` 字段解析；在 `Submitter` 拦截 `dry_run` 提交。<br>3. 编写 `mode` 字段门控的单元测试。 | `rules-generator` 命令；`AttributeRuleLoader`/`Submitter` 拦截逻辑；单元测试代码。 | 自动生成率达 80%；`mode: dry_run` 拦截覆盖率达 100%；预估代码量从 300 行调整为 **~350 行**。 |
| **Phase 2** | 在 YAML 中配置 llm source；激活 `LLMAttributeExtractor` 逻辑，编写端到端测试 | `tests/integration/test_llm_attribute_resolution.py` 覆盖率 90% | 验证 Giga 详情缺乏证据时，發品被 `needs_manual_review` 100% 拦截 |
| **Phase 3** | Submitter 增加变体在线拓扑提取（通过 getCatalogItem 获取 variations）与 parent-child 重复属性求差前置校验 | `VariationHierarchyAuditGate` 类；`amazon_variation_conflict_logs` 表 DDL 迁移 | 拦截 duplicate variation 成功率达 100%；处理 API Rate Limit 逻辑通过 |
