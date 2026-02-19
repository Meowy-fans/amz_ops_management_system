# 1.8 生成亚马逊发品文件模块 - 业务与数据逻辑文档

**版本**: 1.0.0  
**创建日期**: 2025-11-16  
**作者**: 系统分析  
**模块**: ProductListingService

---

## 📑 目录

1. [模块概述](#1-模块概述)
2. [整体业务流程](#2-整体业务流程)
3. [数据流转详解](#3-数据流转详解)
4. [核心组件架构](#4-核心组件架构)
5. [详细步骤分解](#5-详细步骤分解)
6. [数据表依赖关系](#6-数据表依赖关系)
7. [配置文件说明](#7-配置文件说明)
8. [核心算法解析](#8-核心算法解析)
9. [错误处理机制](#9-错误处理机制)
10. [扩展性说明](#10-扩展性说明)

---

## 1. 模块概述

### 1.1 功能定位

**主功能**: 基于指定品类，自动生成符合亚马逊Listing要求的Excel上传文件（.xlsm格式）

**核心价值**:
- 自动化发品流程，减少人工操作
- 智能识别单品和变体，自动分组
- 数据映射准确，符合亚马逊模板规范
- 支持批次管理和日志追踪

### 1.2 适用场景

- **场景一**: 新品上架 - 将库存中符合条件的商品批量生成发品文件
- **场景二**: 分品类发品 - 按品类（如CABINET、HOME_MIRROR）分批上传
- **场景三**: 增补发品 - 为已有变体家族添加新的子SKU

### 1.3 关键约束

| 约束项 | 说明 |
|--------|------|
| 品类必须存在模板 | 系统中必须预先配置该品类的Amazon模板规则 |
| SKU必须有完整数据 | 包括LLM生成的详情、价格、库存等 |
| 变体关联必须准确 | 依赖Giga API的associateProductList字段 |
| 模板文件必须存在 | template_files目录下必须有对应的.xlsm文件 |

---

## 2. 整体业务流程

### 2.1 流程概览

```
┌─────────────────┐
│ 用户选择品类     │
│  (如: CABINET)  │
└────────┬────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤1: 筛选待发品SKU                                      │
│  - 从数据库查询符合条件的meow_sku                         │
│  - 条件: 未在Amazon、非超大件、有可用价格等               │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤2: 获取SKU品类映射                                    │
│  - 将meow_sku映射到standard_category_name                │
│  - 路径: meow_sku → vendor_sku → category_code → 品类   │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤3: 过滤指定品类                                       │
│  - 从所有待发品中筛选出指定品类的SKU                      │
│  - 大小写不敏感比较                                       │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤4: 获取变体关联数据                                   │
│  - 查询每个SKU的associateProductList                      │
│  - 构建变体关系图                                         │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤5: 识别变体家族                                       │
│  - 使用DFS算法找出连通分量                                │
│  - 输出: 单品列表 + 变体家族列表                          │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤6: 加载品类模板规则                                   │
│  - 从amazon_cat_templates表查询                          │
│  - 获取字段定义、有效值、变体映射等                       │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤7: 处理单品                                           │
│  - 获取每个单品的完整数据                                 │
│  - 应用字段映射规则                                       │
│  - 生成数据行                                             │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤8: 处理变体家族                                       │
│  - 为每个家族生成父SKU                                    │
│  - 生成父体数据行（泛化标题）                             │
│  - 生成所有子体数据行                                     │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤9: 合并所有数据行                                     │
│  - single_rows + variation_rows                          │
│  - 验证数据完整性                                         │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤10: 生成Excel文件                                     │
│  - 加载品类模板 (CABINET.xlsm)                           │
│  - 填充数据到Template工作表                              │
│  - 保存到output目录                                      │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────────────────────────────────────────────┐
│ 步骤11: 记录发品日志                                      │
│  - 插入到amz_listing_log表                               │
│  - 状态: GENERATED                                       │
│  - 关联batch_id                                          │
└────────┬───────────────────────────────────────────────┘
         │
         ↓
┌─────────────────┐
│ 返回成功结果     │
│  - 文件路径     │
│  - 统计信息     │
└─────────────────┘
```

### 2.2 成功路径

**输入**: 品类名称（字符串，如 "CABINET"）

**输出**: 结果字典
```python
{
    'success': True,
    'batch_id': UUID('...'),
    'excel_file': '/path/to/output/AmazonUpload_CABINET_20251116_143022_batch_a1b2c3d4.xlsm',
    'single_count': 15,
    'variation_count': 8,
    'total_rows': 47,
    'message': '成功生成 47 行数据'
}
```

### 2.3 异常路径

| 异常情况 | 返回结果 |
|----------|----------|
| 没有待发品SKU | `{'success': False, 'message': '没有待发品SKU'}` |
| 品类无待发品 | `{'success': False, 'message': '品类 XXX 没有待发品SKU'}` |
| 品类无模板 | `{'success': False, 'message': '品类 XXX 没有模板规则'}` |
| 没有生成数据行 | `{'success': False, 'message': '没有生成任何数据行'}` |
| 系统错误 | `{'success': False, 'message': '生成失败: [错误信息]'}` |

---

## 3. 数据流转详解

### 3.1 数据来源表

```
┌─────────────────────────────────────────────────────────┐
│                    数据来源全景图                         │
└─────────────────────────────────────────────────────────┘

meow_sku_map (SKU映射表)
    ↓ 提供: meow_sku ↔ vendor_sku 映射
    │
giga_product_sync_records (Giga商品同步记录)
    ↓ 提供: 
    │  - raw_data (JSONB): 尺寸、重量、图片等
    │  - category_code: 品类代码
    │  - associateProductList: 变体关联
    │  - is_oversize: 是否超大件
    │
supplier_categories_map (品类映射表)
    ↓ 提供: supplier_category_code → standard_category_name
    │
ds_api_product_details (LLM生成详情)
    ↓ 提供:
    │  - product_name: 产品名称
    │  - product_description: 产品描述
    │  - selling_point_1~5: 卖点
    │
product_final_prices (最终售价)
    ↓ 提供: meow_sku → final_price
    │
giga_inventory (库存)
    ↓ 提供: vendor_sku → (quantity + buyer_qty)
    │
giga_product_base_prices (基础价格)
    ↓ 提供: sku_available (价格是否可用)
    │
amz_all_listing_report (Amazon全量报告)
    ↓ 提供: 已发布的SKU列表（用于排除）
    │
amazon_cat_templates (品类模板)
    ↓ 提供:
       - fields: 字段列表
       - field_definitions: 字段定义
       - valid_values: 有效值约束
       - variation_mapping: 变体映射规则
```

### 3.2 数据加工流程

```
原始数据
  ↓
┌─────────────────────────────────────────────────────────┐
│ 阶段1: 数据收集                                           │
│  - 从10+张表联查获取完整产品数据                          │
│  - 结构: ProductDataRepository.get_full_product_data()   │
└─────────────┬───────────────────────────────────────────┘
              │
              ↓
┌─────────────────────────────────────────────────────────┐
│ 阶段2: 字段映射                                           │
│  - 根据amz_mapping.json配置                              │
│  - 映射类型:                                             │
│    * static: 静态值                                      │
│    * direct: 直接字段                                    │
│    * db_field: 数据库字段                                │
│    * jsonb: JSONB路径提取                                │
│    * unit_mapper: 单位转换                               │
│    * category_lookup: 品类查找                           │
│  - 结构: DataMappingHelper.apply_mapping()               │
└─────────────┬───────────────────────────────────────────┘
              │
              ↓
┌─────────────────────────────────────────────────────────┐
│ 阶段3: 变体处理（仅变体商品）                             │
│  - 父体标题泛化 (移除颜色/尺寸描述)                       │
│  - 变体属性格式化 (尺寸取整)                              │
│  - 关系字段填充:                                         │
│    * Relationship Type: Parent/Child                     │
│    * Parent SKU: PARENT-xxxxxxxxxxxx                     │
│  - 结构: VariationHelper                                 │
└─────────────┬───────────────────────────────────────────┘
              │
              ↓
┌─────────────────────────────────────────────────────────┐
│ 阶段4: Excel行生成                                        │
│  - 字段名到值的字典                                       │
│  - 示例:                                                 │
│    {                                                     │
│      'SKU': 'meow2511080spTk',                          │
│      'Product Type': 'CABINET',                         │
│      'Item Name': 'Modern Bathroom...',                 │
│      'Listing Action': 'Create or Replace...',          │
│      'Price': 299.99,                                   │
│      ...                                                │
│    }                                                    │
└─────────────┬───────────────────────────────────────────┘
              │
              ↓
最终Excel文件
```

### 3.3 变体数据特殊处理

**变体识别流程**:

```
Step 1: 构建关联图
───────────────────
meow_sku_A (vendor_sku_A) → [vendor_sku_B, vendor_sku_C]
meow_sku_B (vendor_sku_B) → [vendor_sku_A, vendor_sku_C]
meow_sku_C (vendor_sku_C) → [vendor_sku_A, vendor_sku_B]
meow_sku_D (vendor_sku_D) → []

Step 2: 转换为无向图
───────────────────
vendor_sku_A ↔ vendor_sku_B
vendor_sku_A ↔ vendor_sku_C
vendor_sku_B ↔ vendor_sku_C
vendor_sku_D (孤立节点)

Step 3: DFS查找连通分量
───────────────────────
连通分量1: [vendor_sku_A, vendor_sku_B, vendor_sku_C]
孤立节点: vendor_sku_D

Step 4: 转回meow_sku并分类
───────────────────────────
变体家族: [[meow_sku_A, meow_sku_B, meow_sku_C]]
单品: [meow_sku_D]
```

**变体Excel行生成**:

```
变体家族: [meow_sku_001, meow_sku_002, meow_sku_003]
         ↓
┌────────────────────────────────────────────────────┐
│ 生成父体行                                          │
│  - SKU: PARENT-A1B2C3D4E5F6                       │
│  - Relationship Type: Parent                       │
│  - Item Name: Modern Cabinet (泛化标题)            │
│  - 其他字段: 使用第一个子SKU的数据                  │
└────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────┐
│ 生成子体行1                                         │
│  - SKU: meow_sku_001                              │
│  - Parent SKU: PARENT-A1B2C3D4E5F6                │
│  - Relationship Type: Child                        │
│  - Item Name: Modern Cabinet - White              │
│  - Color: White                                    │
└────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────┐
│ 生成子体行2                                         │
│  - SKU: meow_sku_002                              │
│  - Parent SKU: PARENT-A1B2C3D4E5F6                │
│  - Relationship Type: Child                        │
│  - Item Name: Modern Cabinet - Black              │
│  - Color: Black                                    │
└────────────────────────────────────────────────────┘
         ↓
┌────────────────────────────────────────────────────┐
│ 生成子体行3                                         │
│  - SKU: meow_sku_003                              │
│  - Parent SKU: PARENT-A1B2C3D4E5F6                │
│  - Relationship Type: Child                        │
│  - Item Name: Modern Cabinet - Gray               │
│  - Color: Gray                                     │
└────────────────────────────────────────────────────┘
```

---

## 4. 核心组件架构

### 4.1 组件职责划分

```
ProductListingService (服务层)
├── 职责: 业务流程编排、事务管理
├── 依赖:
│   ├── ProductListingRepository (数据查询)
│   ├── ProductDataRepository (商品数据)
│   ├── AmzTemplateRepository (模板规则)
│   ├── AmzListingLogRepository (日志记录)
│   ├── DataMappingHelper (字段映射)
│   ├── ExcelGenerator (文件生成)
│   └── VariationHelper (变体处理)
└── 核心方法: generate_listings_by_category()

ProductListingRepository (仓库层)
├── 职责: 复杂的多表联查
├── 方法:
│   ├── get_pending_listing_skus(): 筛选待发品SKU
│   ├── get_variation_data(): 获取变体关联
│   └── get_sku_to_category_mapping(): SKU品类映射
└── 特点: 纯数据访问，无业务逻辑

ProductDataRepository (仓库层)
├── 职责: 获取单个SKU的完整数据
├── 方法:
│   └── get_full_product_data(meow_sku): 10+表联查
└── 返回: 包含所有字段的字典

AmzTemplateRepository (仓库层)
├── 职责: 品类模板规则管理
├── 方法:
│   ├── find_template_by_category(): 查询模板规则
│   ├── save_parsed_data(): 保存模板解析结果
│   └── update_field_definitions_by_id(): 更新字段定义
└── 数据表: amazon_cat_templates

AmzListingLogRepository (仓库层)
├── 职责: 发品日志管理
├── 方法:
│   ├── bulk_insert_log(): 批量插入日志
│   ├── find_log_for_family(): 查找家族日志
│   └── bulk_update_status_to_listed(): 更新状态
└── 数据表: amz_listing_log

DataMappingHelper (工具层)
├── 职责: 字段映射规则执行
├── 配置: amz_mapping.json
├── 方法:
│   ├── apply_mapping(): 应用映射规则
│   ├── get_llm_tasks(): 提取LLM任务
│   └── _map_single_field(): 单字段映射
└── 支持类型: 9种映射类型

ExcelGenerator (工具层)
├── 职责: Excel文件生成
├── 方法:
│   ├── generate_excel(): 生成Excel
│   ├── _parse_header(): 解析表头
│   └── _fill_data(): 填充数据
├── 模板: template_files/*.xlsm
└── 输出: output/*.xlsm

VariationHelper (工具层)
├── 职责: 变体识别和处理
├── 方法:
│   ├── find_variation_families(): DFS识别家族
│   ├── format_variation_attributes(): 格式化属性
│   └── generalize_parent_title(): 泛化标题
└── 算法: 图论DFS
```

### 4.2 数据流向

```
用户输入 (category_name)
      ↓
ProductListingService
      ↓
┌─────┴────────────────────────────────────┐
│                                          │
↓                                          ↓
ProductListingRepository         AmzTemplateRepository
(筛选SKU、变体数据)                (加载模板规则)
      ↓                                    ↓
VariationHelper                   DataMappingHelper
(识别变体家族)                     (字段映射配置)
      ↓                                    ↓
ProductDataRepository
(获取完整商品数据)
      ↓
DataMappingHelper
(应用映射规则)
      ↓
ExcelGenerator
(生成Excel文件)
      ↓
AmzListingLogRepository
(记录日志)
      ↓
返回结果
```

### 4.3 配置文件结构

```
project_root/
├── config/
│   └── amz_listing_data_mapping/
│       ├── amz_mapping.json          # 字段映射配置
│       └── category_mapping.json     # 品类映射配置
├── template_files/
│   ├── CABINET.xlsm                  # 柜子品类模板
│   ├── HOME_MIRROR.xlsm              # 镜子品类模板
│   └── ...                           # 其他品类模板
└── output/
    └── AmazonUpload_*.xlsm           # 生成的文件
```

---

## 5. 详细步骤分解

### 步骤1: 筛选待发品SKU

**SQL查询**:
```sql
SELECT DISTINCT m.meow_sku
FROM meow_sku_map m
    LEFT JOIN amz_all_listing_report r 
        ON m.meow_sku = r."seller-sku"
    JOIN giga_product_sync_records psr 
        ON m.vendor_sku = psr.giga_sku 
        AND m.vendor_source = 'giga'
    JOIN giga_product_base_prices pbp 
        ON m.vendor_sku = pbp.giga_sku
WHERE r."seller-sku" IS NULL                                    -- 未在Amazon
  AND psr.is_oversize IS NOT TRUE                               -- 非超大件
  AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL' -- 普通卖家
  AND pbp.sku_available IS TRUE                                 -- 有可用价格
ORDER BY m.meow_sku;
```

**业务规则**:
1. **未在Amazon**: 通过LEFT JOIN检查是否在amz_all_listing_report中
2. **非超大件**: is_oversize != TRUE（超大件运费高，不适合普通发品）
3. **普通卖家**: sellerType = 'GENERAL'（排除品牌商品）
4. **有可用价格**: sku_available = TRUE（确保能定价）

**输出示例**:
```python
['meow2511080spTk', 'meow251108yvrSP', 'meow251108lu7Vo', ...]
```

---

### 步骤2: 获取SKU品类映射

**SQL查询**:
```sql
SELECT DISTINCT 
    m.meow_sku,
    scm.standard_category_name
FROM meow_sku_map m
    JOIN giga_product_sync_records psr 
        ON m.vendor_sku = psr.giga_sku 
        AND m.vendor_source = 'giga'
    LEFT JOIN supplier_categories_map scm 
        ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
        AND scm.supplier_platform = 'giga'
WHERE m.meow_sku = ANY(:meow_sku_list)
ORDER BY m.meow_sku;
```

**映射路径**:
```
meow_sku → vendor_sku (通过meow_sku_map)
         ↓
vendor_sku → category_code (通过giga_product_sync_records)
         ↓
category_code → standard_category_name (通过supplier_categories_map)
```

**输出示例**:
```python
[
    ('meow2511080spTk', 'CABINET'),
    ('meow251108yvrSP', 'CABINET'),
    ('meow251108lu7Vo', 'HOME_MIRROR'),
    ('meow251108UzmV5', None),  # 未映射品类
    ...
]
```

---

### 步骤3: 过滤指定品类

**代码逻辑**:
```python
pending_skus = [
    sku for sku, cat in sku_category_mapping 
    if cat and cat.upper() == category_name.upper()
]
```

**说明**:
- 大小写不敏感比较（upper()）
- 过滤掉未映射品类的SKU（cat为None）
- 返回仅属于指定品类的SKU列表

**输出示例** (category_name='CABINET'):
```python
['meow2511080spTk', 'meow251108yvrSP', ...]
```

---

### 步骤4: 获取变体关联数据

**SQL查询**:
```sql
WITH latest_records AS (
    SELECT 
        giga_sku,
        raw_data,
        ROW_NUMBER() OVER(PARTITION BY giga_sku ORDER BY id DESC) as rn
    FROM giga_product_sync_records
)
SELECT 
    m.meow_sku,
    m.vendor_sku,
    COALESCE(lr.raw_data -> 'associateProductList', '[]'::jsonb) AS associate_list
FROM meow_sku_map m
    JOIN latest_records lr 
        ON m.vendor_sku = lr.giga_sku
WHERE lr.rn = 1
  AND m.meow_sku = ANY(:meow_sku_list);
```

**关键点**:
1. **窗口函数**: 确保每个giga_sku只取最新记录（id DESC）
2. **JSONB提取**: raw_data -> 'associateProductList'
3. **容错处理**: COALESCE保证空值返回[]

**输出示例**:
```python
[
    ('meow2511080spTk', 'W2615S00273', ['W2615S00274', 'W2615S00275']),
    ('meow251108yvrSP', 'W2615S00274', ['W2615S00273', 'W2615S00275']),
    ('meow251108lu7Vo', 'W2615S00275', ['W2615S00273', 'W2615S00274']),
    ('meow251108UzmV5', 'W8888S00001', []),  # 单品
    ...
]
```

---

### 步骤5: 识别变体家族

**算法**: 图论深度优先搜索（DFS）

**代码流程**:
```python
# 1. 构建映射
meow_to_vendor = {meow: vendor for meow, vendor, _ in variation_data}
vendor_to_meow = {vendor: meow for meow, vendor, _ in variation_data}

# 2. 构建邻接表（无向图）
adj_list = defaultdict(list)
for _, vendor_sku, assoc_list in variation_data:
    for assoc_vendor in assoc_list:
        if assoc_vendor in vendor_to_meow:
            # 双向边
            adj_list[vendor_sku].append(assoc_vendor)
            adj_list[assoc_vendor].append(vendor_sku)

# 3. DFS查找连通分量
visited = set()
single_products = []
variation_families = []

for vendor_sku in all_vendor_skus:
    if vendor_sku in visited:
        continue
    
    if not adj_list.get(vendor_sku):
        # 孤立节点 → 单品
        single_products.append(vendor_to_meow[vendor_sku])
        visited.add(vendor_sku)
    else:
        # 执行DFS
        component = []
        _dfs(vendor_sku, adj_list, visited, component)
        
        component_meow = [vendor_to_meow[v] for v in component]
        
        if len(component_meow) > 1:
            variation_families.append(component_meow)
        else:
            single_products.extend(component_meow)
```

**DFS递归**:
```python
def _dfs(node, adj_list, visited, component):
    visited.add(node)
    component.append(node)
    
    for neighbor in adj_list.get(node, []):
        if neighbor not in visited:
            _dfs(neighbor, adj_list, visited, component)
```

**示例**:

```
输入:
[
    ('SKU-A', 'V-A', ['V-B', 'V-C']),
    ('SKU-B', 'V-B', ['V-A', 'V-C']),
    ('SKU-C', 'V-C', ['V-A', 'V-B']),
    ('SKU-D', 'V-D', []),
    ('SKU-E', 'V-E', ['V-F']),
    ('SKU-F', 'V-F', ['V-E'])
]

输出:
single_products = ['SKU-D']
variation_families = [
    ['SKU-A', 'SKU-B', 'SKU-C'],
    ['SKU-E', 'SKU-F']
]
```

---

### 步骤6: 加载品类模板规则

**SQL查询**:
```sql
SELECT 
    fields, 
    field_definitions, 
    valid_values, 
    variation_mapping, 
    priority_themes
FROM amazon_cat_templates
WHERE LOWER(category) = LOWER(:category)
ORDER BY id DESC 
LIMIT 1;
```

**返回数据结构**:
```python
{
    "fields": [
        "SKU",
        "Product Type",
        "Item Name",
        "Listing Action",
        ...
    ],
    "field_definitions": {
        "SKU": {
            "required": true,
            "type": "string",
            "max_length": 40
        },
        "Color": {
            "required": false,
            "type": "string",
            "valid_values": ["White", "Black", "Gray", ...]
        },
        ...
    },
    "valid_values": [
        {
            "attribute": "Color",
            "values": ["White", "Black", "Gray", "Natural", ...]
        },
        {
            "attribute": "Material",
            "values": ["Wood", "MDF", "Particle Board", ...]
        },
        ...
    ],
    "variation_mapping": {
        "color": "Color",
        "size": "Size",
        ...
    },
    "priority_themes": ["COLOR", "SIZE"]
}
```

**用途**:
- **fields**: 确定Excel列顺序
- **field_definitions**: 数据验证规则
- **valid_values**: LLM生成时的约束
- **variation_mapping**: 变体属性映射
- **priority_themes**: 变体主题优先级

---

### 步骤7: 处理单品

**伪代码**:
```python
for meow_sku in single_skus:
    # 1. 获取完整产品数据
    product_data = product_data_repo.get_full_product_data(meow_sku)
    
    # 2. 应用字段映射
    mapped_data = data_mapper.apply_mapping(
        product_data,
        template_rules,
        category_config
    )
    
    # 3. 添加单品特定字段
    mapped_data['Listing Action'] = 'Create or Replace (Full Update)'
    
    # 4. 添加到行列表
    rows.append(mapped_data)
```

**数据示例**:

`product_data` (原始):
```python
{
    'vendor_sku': 'W2615S00273',
    'product_name': 'Modern Bathroom Vanity with Mirror',
    'product_description': 'This elegant bathroom...',
    'selling_point_1': 'Durable construction',
    'selling_point_2': 'Easy to assemble',
    'selling_point_3': 'Modern design',
    'selling_point_4': 'Water resistant',
    'selling_point_5': 'Space saving',
    'raw_data': {
        'productTitle': 'Bathroom Vanity Set',
        'length': 24,
        'width': 18,
        'height': 32,
        'lengthUnit': 'in',
        'weight': 45,
        'weightUnit': 'lb',
        'imageList': [...],
        ...
    },
    'final_price': 299.99,
    'total_quantity': 150
}
```

`mapped_data` (映射后):
```python
{
    'SKU': 'meow2511080spTk',
    'Product Type': 'CABINET',
    'Item Name': 'Modern Bathroom Vanity with Mirror',
    'Product Description': 'This elegant bathroom...',
    'Bullet Point 1': 'Durable construction',
    'Bullet Point 2': 'Easy to assemble',
    'Bullet Point 3': 'Modern design',
    'Bullet Point 4': 'Water resistant',
    'Bullet Point 5': 'Space saving',
    'Main Image URL': 'https://...',
    'Other Image URL1': 'https://...',
    'Item Length': 24,
    'Item Width': 18,
    'Item Height': 32,
    'Item Dimensions Unit of Measure': 'Inches',
    'Item Weight': 45,
    'Item Weight Unit of Measure': 'Pounds',
    'Standard Price': 299.99,
    'Quantity': 150,
    'Listing Action': 'Create or Replace (Full Update)',
    ...
}
```

---

### 步骤8: 处理变体家族

**伪代码**:
```python
for family_skus in variation_families:
    # 1. 生成父SKU
    parent_sku = f"PARENT-{uuid.uuid4().hex[:12].upper()}"
    
    # 2. 获取第一个子SKU数据作为父体基础
    first_product = product_data_repo.get_full_product_data(family_skus[0])
    
    # 3. 生成父体行
    parent_row = data_mapper.apply_mapping(first_product, template_rules, category_config)
    parent_row['SKU'] = parent_sku
    parent_row['Listing Action'] = 'Create or Replace (Full Update)'
    parent_row['Relationship Type'] = 'Parent'
    
    # 4. 泛化标题
    parent_row['Item Name'] = variation_helper.generalize_parent_title(
        parent_row['Item Name']
    )
    
    rows.append(parent_row)
    
    # 5. 生成所有子体行
    for child_sku in family_skus:
        child_product = product_data_repo.get_full_product_data(child_sku)
        child_row = data_mapper.apply_mapping(child_product, template_rules, category_config)
        
        child_row['Listing Action'] = 'Create or Replace (Full Update)'
        child_row['Relationship Type'] = 'Child'
        child_row['Parent SKU'] = parent_sku
        
        rows.append(child_row)
        
        # 6. 记录日志
        logs.append({
            'meow_sku': child_sku,
            'parent_sku': parent_sku,
            'variation_attributes': {},
            'listing_batch_id': batch_id,
            'status': 'GENERATED',
            'variation_theme': None
        })
```

**标题泛化示例**:
```python
# 输入
"Modern Bathroom Vanity - White"
"24 Inch Vanity with Mirror - Black"
"Bathroom Cabinet Set - Gray"

# 输出 (移除 "- 颜色/风格" 部分)
"Modern Bathroom Vanity"
"24 Inch Vanity with Mirror"
"Bathroom Cabinet Set"
```

**变体行示例**:

父体行:
```python
{
    'SKU': 'PARENT-A1B2C3D4E5F6',
    'Product Type': 'CABINET',
    'Item Name': 'Modern Bathroom Vanity',  # 泛化后
    'Relationship Type': 'Parent',
    'Listing Action': 'Create or Replace (Full Update)',
    'Product Description': '...',
    'Main Image URL': '...',
    # 其他字段...
}
```

子体行1:
```python
{
    'SKU': 'meow2511080spTk',
    'Parent SKU': 'PARENT-A1B2C3D4E5F6',
    'Product Type': 'CABINET',
    'Item Name': 'Modern Bathroom Vanity - White',
    'Relationship Type': 'Child',
    'Listing Action': 'Create or Replace (Full Update)',
    'Color': 'White',
    'Standard Price': 299.99,
    'Quantity': 150,
    # 其他字段...
}
```

子体行2:
```python
{
    'SKU': 'meow251108yvrSP',
    'Parent SKU': 'PARENT-A1B2C3D4E5F6',
    'Product Type': 'CABINET',
    'Item Name': 'Modern Bathroom Vanity - Black',
    'Relationship Type': 'Child',
    'Listing Action': 'Create or Replace (Full Update)',
    'Color': 'Black',
    'Standard Price': 329.99,
    'Quantity': 120,
    # 其他字段...
}
```

---

### 步骤9: 合并所有数据行

**代码**:
```python
all_rows = single_rows + variation_rows

if not all_rows:
    return {
        'success': False,
        'message': "没有生成任何数据行"
    }

logger.info(f"总共生成 {len(all_rows)} 行数据")
```

**数据结构**:
```python
all_rows = [
    # 单品行
    {'SKU': 'meow251108xxx', 'Item Name': '...', ...},
    {'SKU': 'meow251108yyy', 'Item Name': '...', ...},
    
    # 变体家族1 (父体 + 子体)
    {'SKU': 'PARENT-AAA', 'Relationship Type': 'Parent', ...},
    {'SKU': 'meow251108zzz', 'Parent SKU': 'PARENT-AAA', 'Relationship Type': 'Child', ...},
    {'SKU': 'meow251108www', 'Parent SKU': 'PARENT-AAA', 'Relationship Type': 'Child', ...},
    
    # 变体家族2
    {'SKU': 'PARENT-BBB', 'Relationship Type': 'Parent', ...},
    {'SKU': 'meow251108ppp', 'Parent SKU': 'PARENT-BBB', 'Relationship Type': 'Child', ...},
    ...
]
```

---

### 步骤10: 生成Excel文件

**流程详解**:

```python
# 1. 定位模板文件
template_filename = f"{category_name.upper()}.xlsm"
template_path = self.template_base_path / template_filename
# 例如: /project_root/template_files/CABINET.xlsm

# 2. 加载模板 (保留VBA宏)
wb = openpyxl.load_workbook(template_path, keep_vba=True)
ws = wb["Template"]

# 3. 解析表头 (第4行)
header_map = {}
for col_idx in range(1, ws.max_column + 1):
    header_value = ws.cell(row=4, column=col_idx).value
    if header_value:
        if header_value not in header_map:
            header_map[header_value] = []
        header_map[header_value].append(col_idx)

# 例如:
# {
#     'SKU': [1],
#     'Product Type': [2],
#     'Item Name': [3],
#     'Bullet Point': [15, 16, 17, 18, 19],  # 多列
#     ...
# }

# 4. 填充数据 (从第7行开始)
for row_idx, row_data in enumerate(all_rows):
    current_row = 7 + row_idx
    
    for field_name, value in row_data.items():
        col_indices = header_map.get(field_name)
        
        if not col_indices:
            continue
        
        # 处理列表类型（如Bullet Point）
        if isinstance(value, list):
            for item_idx, item_value in enumerate(value):
                if item_idx < len(col_indices):
                    col_idx = col_indices[item_idx]
                    ws.cell(row=current_row, column=col_idx, value=item_value)
        else:
            # 单值，写入第一列
            col_idx = col_indices[0]
            ws.cell(row=current_row, column=col_idx, value=value)

# 5. 生成文件名
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
batch_short = str(batch_id)[:8]
output_filename = f"AmazonUpload_{category_name}_{timestamp}_batch_{batch_short}.xlsm"

# 6. 保存文件
output_path = self.output_base_path / output_filename
wb.save(output_path)
```

**Excel结构**:
```
Sheet: Template
Row 1-3: 说明信息
Row 4: 表头
Row 5-6: 示例数据（可能为空）
Row 7+: 实际数据行

列结构:
A列: SKU
B列: Product Type
C列: Item Name
...
O-S列: Bullet Point 1-5 (5列)
...
```

**输出文件示例**:
```
/project_root/output/AmazonUpload_CABINET_20251116_143022_batch_a1b2c3d4.xlsm
```

---

### 步骤11: 记录发品日志

**代码**:
```python
all_logs = []

# 单品日志
for sku in single_skus:
    all_logs.append({
        'meow_sku': sku,
        'parent_sku': 'SINGLE_PRODUCT',  # 固定标识
        'variation_attributes': {},
        'listing_batch_id': batch_id,
        'status': 'GENERATED',
        'variation_theme': None
    })

# 变体日志（在步骤8中已构建）
for log in variation_logs:
    log['listing_batch_id'] = batch_id
    all_logs.append(log)

# 批量插入
if all_logs:
    self.listing_log_repo.bulk_insert_log(all_logs)
```

**SQL插入**:
```sql
INSERT INTO amz_listing_log (
    meow_sku, 
    parent_sku, 
    variation_attributes,
    listing_batch_id, 
    status, 
    variation_theme
)
VALUES (
    :meow_sku, 
    :parent_sku, 
    :variation_attributes,
    :listing_batch_id, 
    :status, 
    :variation_theme
)
ON CONFLICT (meow_sku) DO UPDATE SET
    parent_sku = EXCLUDED.parent_sku,
    variation_attributes = EXCLUDED.variation_attributes,
    listing_batch_id = EXCLUDED.listing_batch_id,
    status = EXCLUDED.status,
    variation_theme = EXCLUDED.variation_theme,
    created_at = CURRENT_TIMESTAMP;
```

**日志记录示例**:
```python
[
    # 单品
    {
        'meow_sku': 'meow251108xxx',
        'parent_sku': 'SINGLE_PRODUCT',
        'variation_attributes': {},
        'listing_batch_id': UUID('91acec9c-1ca6-48d2-9f58-fbb5a6bfa230'),
        'status': 'GENERATED',
        'variation_theme': None
    },
    
    # 变体子SKU
    {
        'meow_sku': 'meow2511080spTk',
        'parent_sku': 'PARENT-A1B2C3D4E5F6',
        'variation_attributes': {},
        'listing_batch_id': UUID('91acec9c-1ca6-48d2-9f58-fbb5a6bfa230'),
        'status': 'GENERATED',
        'variation_theme': 'COLOR'
    },
    ...
]
```

**说明**:
- **parent_sku**:
  - 单品: 固定为 `'SINGLE_PRODUCT'`
  - 变体: 实际的父SKU (如 `'PARENT-A1B2C3D4E5F6'`)
- **status**: 初始为 `'GENERATED'`，待上传后更新为 `'LISTED'`
- **ON CONFLICT**: 如果SKU已存在，则更新记录

---

## 6. 数据表依赖关系

### 6.1 表关系图

```
┌───────────────────────┐
│ meow_sku_map          │ ← 核心映射表
│ - meow_sku (PK)       │
│ - vendor_sku          │
│ - vendor_source       │
└──────┬────────────────┘
       │
       ├──→ ┌───────────────────────────┐
       │    │ ds_api_product_details    │ ← LLM生成详情
       │    │ - sku_id (vendor_sku)     │
       │    │ - product_name            │
       │    │ - product_description     │
       │    │ - selling_point_1~5       │
       │    └───────────────────────────┘
       │
       ├──→ ┌───────────────────────────┐
       │    │ giga_product_sync_records │ ← Giga原始数据
       │    │ - giga_sku (vendor_sku)   │
       │    │ - category_code           │
       │    │ - raw_data (JSONB)        │
       │    │ - is_oversize             │
       │    └──────┬────────────────────┘
       │           │
       │           └──→ ┌─────────────────────────────┐
       │                │ supplier_categories_map     │ ← 品类映射
       │                │ - supplier_category_code    │
       │                │ - standard_category_name    │
       │                └─────────────────────────────┘
       │
       ├──→ ┌───────────────────────────┐
       │    │ product_final_prices      │ ← 最终售价
       │    │ - meow_sku                │
       │    │ - final_price             │
       │    └───────────────────────────┘
       │
       ├──→ ┌───────────────────────────┐
       │    │ giga_inventory            │ ← 库存
       │    │ - giga_sku (vendor_sku)   │
       │    │ - quantity                │
       │    │ - buyer_qty               │
       │    └───────────────────────────┘
       │
       └──→ ┌───────────────────────────┐
            │ giga_product_base_prices  │ ← 基础价格
            │ - giga_sku (vendor_sku)   │
            │ - sku_available           │
            └───────────────────────────┘

┌───────────────────────────┐
│ amz_all_listing_report    │ ← Amazon全量报告 (排除已发布)
│ - seller-sku (meow_sku)   │
│ - status                  │
└───────────────────────────┘

┌───────────────────────────┐
│ amazon_cat_templates      │ ← 品类模板规则
│ - category                │
│ - fields (JSONB)          │
│ - field_definitions       │
│ - valid_values            │
│ - variation_mapping       │
└───────────────────────────┘

┌───────────────────────────┐
│ amz_listing_log           │ ← 发品日志 (记录输出)
│ - meow_sku (PK)           │
│ - parent_sku              │
│ - listing_batch_id        │
│ - status                  │
└───────────────────────────┘
```

### 6.2 表字段详解

#### **meow_sku_map** (SKU映射表)

| 字段 | 类型 | 说明 | 用途 |
|------|------|------|------|
| meow_sku | VARCHAR(100) PK | 内部SKU | 唯一标识符 |
| vendor_sku | VARCHAR(100) | 供应商SKU | 关联到Giga SKU |
| vendor_source | VARCHAR(50) | 供应商来源 | 固定为'giga' |

**关联**:
- → ds_api_product_details: `vendor_sku = sku_id`
- → giga_product_sync_records: `vendor_sku = giga_sku`
- → giga_inventory: `vendor_sku = giga_sku`
- → giga_product_base_prices: `vendor_sku = giga_sku`

---

#### **ds_api_product_details** (LLM生成详情)

| 字段 | 类型 | 说明 | 映射目标 |
|------|------|------|----------|
| sku_id | VARCHAR | vendor_sku | - |
| product_name | TEXT | 产品名称 | Item Name |
| product_description | TEXT | 产品描述 | Product Description |
| selling_point_1 | TEXT | 卖点1 | Bullet Point 1 |
| selling_point_2 | TEXT | 卖点2 | Bullet Point 2 |
| selling_point_3 | TEXT | 卖点3 | Bullet Point 3 |
| selling_point_4 | TEXT | 卖点4 | Bullet Point 4 |
| selling_point_5 | TEXT | 卖点5 | Bullet Point 5 |

**生成方式**: 通过LLM（DeepSeek/Qwen）基于Giga原始数据生成

---

#### **giga_product_sync_records** (Giga原始数据)

| 字段 | 类型 | 说明 | 重要子字段 |
|------|------|------|-----------|
| giga_sku | VARCHAR | Giga SKU | - |
| category_code | VARCHAR | 品类代码 | 用于映射到standard_category |
| raw_data | JSONB | 原始JSON数据 | 详见下方 |
| is_oversize | BOOLEAN | 是否超大件 | 筛选条件 |

**raw_data重要子字段**:
```json
{
    "productTitle": "商品标题",
    "sellerInfo": {
        "sellerType": "GENERAL"  // 卖家类型
    },
    "associateProductList": ["SKU1", "SKU2"],  // 变体关联
    "imageList": ["url1", "url2", ...],        // 图片列表
    "length": 24,            // 长度
    "width": 18,             // 宽度
    "height": 32,            // 高度
    "lengthUnit": "in",      // 单位
    "weight": 45,            // 重量
    "weightUnit": "lb",      // 单位
    "assembledWeight": 50,   // 组装后重量
    "comboFlag": true/false, // 是否组合商品
    "comboInfo": [           // 组合商品详情
        {"weight": 25, "length": 12, ...},
        ...
    ]
}
```

---

#### **supplier_categories_map** (品类映射表)

| 字段 | 类型 | 说明 |
|------|------|------|
| supplier_platform | VARCHAR | 供应商平台 (giga) |
| supplier_category_code | VARCHAR | 供应商品类代码 |
| standard_category_name | VARCHAR | 标准品类名称 |
| supplier_category_name | VARCHAR | 供应商品类名称 |

**映射关系**:
```
supplier_category_code (如: CAB001)
         ↓
standard_category_name (如: CABINET)
```

---

#### **product_final_prices** (最终售价)

| 字段 | 类型 | 说明 | 映射目标 |
|------|------|------|----------|
| meow_sku | VARCHAR | 内部SKU | - |
| final_price | DECIMAL | 最终售价 | Standard Price |

**计算方式**: 基于成本 + 利润率自动计算

---

#### **giga_inventory** (库存)

| 字段 | 类型 | 说明 | 计算公式 |
|------|------|------|----------|
| giga_sku | VARCHAR | Giga SKU | - |
| quantity | INT | 仓库库存 | - |
| buyer_qty | INT | 在途库存 | - |
| **total_quantity** | INT | 总库存 | `quantity + buyer_qty` |

**映射目标**: Quantity字段

---

#### **amazon_cat_templates** (品类模板规则)

| 字段 | 类型 | 说明 |
|------|------|------|
| category | VARCHAR | 品类名称 (CABINET, HOME_MIRROR) |
| template_name | VARCHAR | 模板文件名 |
| fields | JSONB | 字段列表 |
| field_definitions | JSONB | 字段定义 (类型、必填、长度等) |
| valid_values | JSONB | 有效值约束 |
| variation_mapping | JSONB | 变体属性映射规则 |
| priority_themes | JSONB | 优先变体主题 |

**示例数据**: 见步骤6

---

#### **amz_listing_log** (发品日志)

| 字段 | 类型 | 说明 | 取值 |
|------|------|------|------|
| meow_sku | VARCHAR PK | 内部SKU | - |
| parent_sku | VARCHAR | 父SKU | 'SINGLE_PRODUCT' 或实际父SKU |
| variation_attributes | JSONB | 变体属性 | {} 或实际属性 |
| listing_batch_id | UUID | 批次ID | 生成的UUID |
| status | VARCHAR | 状态 | 'GENERATED' / 'LISTED' |
| variation_theme | VARCHAR | 变体主题 | 'COLOR' / 'SIZE' / 'COLOR/SIZE' / NULL |
| created_at | TIMESTAMP | 创建时间 | - |
| updated_at | TIMESTAMP | 更新时间 | - |

**状态流转**:
```
GENERATED (生成文件) → LISTED (上传到Amazon)
```

---

## 7. 配置文件说明

### 7.1 amz_mapping.json (字段映射配置)

**路径**: `config/amz_listing_data_mapping/amz_mapping.json`

**结构**:
```json
{
    "mappings": {
        "字段名": {
            "source_type": "映射类型",
            "参数": "值",
            ...
        }
    }
}
```

**映射类型详解**:

#### 1. **static** (静态值)
```json
"Listing Action": {
    "source_type": "static",
    "value": "Create or Replace (Full Update)"
}
```
用途: 固定值，不随产品变化

---

#### 2. **direct** (直接字段)
```json
"SKU": {
    "source_type": "direct",
    "value": "meow_sku"
}
```
用途: 直接从product_data中取值，key为字段名

---

#### 3. **db_field** (数据库字段)
```json
"Item Name": {
    "source_type": "db_field",
    "field": "product_name"
}
```
用途: 从product_data中取特定字段

---

#### 4. **db_field_multiple** (多个数据库字段)
```json
"Bullet Point": {
    "source_type": "db_field_multiple",
    "fields": [
        "selling_point_1",
        "selling_point_2",
        "selling_point_3",
        "selling_point_4",
        "selling_point_5"
    ]
}
```
用途: 取多个字段组成列表（如Bullet Point有5列）

---

#### 5. **jsonb** (JSONB路径提取)
```json
"Main Image URL": {
    "source_type": "jsonb",
    "json_path": "imageList.0"
}
```
用途: 从raw_data中按路径提取值  
路径格式: `key1.key2.index`

---

#### 6. **jsonb_array** (JSONB数组)
```json
"Other Image URL": {
    "source_type": "jsonb_array",
    "json_path": "imageList"
}
```
用途: 提取完整数组（如图片列表）

---

#### 7. **package_dimension** (包装尺寸)
```json
"Package Length": {
    "source_type": "package_dimension",
    "dimension": "length"
}
```
用途: 提取尺寸，优先从comboInfo[0]取值

---

#### 8. **item_dimension** (产品尺寸)
```json
"Item Length": {
    "source_type": "item_dimension",
    "dimension": "length"
}
```
用途: 直接从raw_data提取，过滤"Not Applicable"

---

#### 9. **unit_mapper** (单位映射)
```json
"Item Dimensions Unit of Measure": {
    "source_type": "unit_mapper",
    "unit_type": "dimension"
}
```
用途: 转换单位（如 "in" → "Inches", "lb" → "Pounds"）

---

#### 10. **summed_weight** (重量求和)
```json
"Item Weight": {
    "source_type": "summed_weight",
    "weight_type": "item"
}
```
用途: 组合商品时求和多个部件的重量

---

#### 11. **category_lookup** (品类查找)
```json
"Product Tax Code": {
    "source_type": "category_lookup",
    "lookup_key": "tax_code"
}
```
用途: 从category_mapping.json中查找品类相关配置

---

#### 12. **field_reference** (字段引用)
```json
"Package Width": {
    "source_type": "field_reference",
    "field": "Item Width"
}
```
用途: 引用已映射的其他字段值

---

### 7.2 category_mapping.json (品类配置)

**路径**: `config/amz_listing_data_mapping/category_mapping.json`

**结构**:
```json
{
    "CABINET": {
        "tax_code": "A_GEN_NOTAX",
        "product_type_override": "CABINET",
        "default_material": "Wood",
        ...
    },
    "HOME_MIRROR": {
        "tax_code": "A_GEN_NOTAX",
        "product_type_override": "MIRROR",
        ...
    }
}
```

**用途**: 
- 品类特定的配置项
- 配合 `category_lookup` 映射类型使用

---

## 8. 核心算法解析

### 8.1 变体识别算法（图论DFS）

**问题建模**:
- **图**: 无向图
- **节点**: vendor_sku (供应商SKU)
- **边**: associateProductList中的关联关系
- **连通分量**: 变体家族
- **孤立节点**: 单品

**算法复杂度**:
- **时间复杂度**: O(V + E)
  - V: 节点数（SKU数量）
  - E: 边数（关联关系数）
- **空间复杂度**: O(V)
  - visited集合、邻接表、递归栈

**伪代码**:
```python
def find_variation_families(variation_data):
    # 构建邻接表
    adj_list = build_adjacency_list(variation_data)
    
    visited = set()
    single_products = []
    variation_families = []
    
    for node in all_nodes:
        if node in visited:
            continue
        
        if not adj_list[node]:
            # 孤立节点
            single_products.append(node)
            visited.add(node)
        else:
            # DFS查找连通分量
            component = []
            dfs(node, adj_list, visited, component)
            
            if len(component) > 1:
                variation_families.append(component)
            else:
                single_products.extend(component)
    
    return single_products, variation_families

def dfs(node, adj_list, visited, component):
    visited.add(node)
    component.append(node)
    
    for neighbor in adj_list[node]:
        if neighbor not in visited:
            dfs(neighbor, adj_list, visited, component)
```

**示例演示**:

```
输入数据:
SKU-A (V-A) → [V-B, V-C]
SKU-B (V-B) → [V-A, V-C]
SKU-C (V-C) → [V-A, V-B]
SKU-D (V-D) → []
SKU-E (V-E) → [V-F]
SKU-F (V-F) → [V-E]

邻接表:
V-A: [V-B, V-C]
V-B: [V-A, V-C]
V-C: [V-A, V-B]
V-D: []
V-E: [V-F]
V-F: [V-E]

DFS过程:
1. 从V-A开始 → 访问V-A, V-B, V-C → 连通分量1
2. V-D孤立 → 单品
3. 从V-E开始 → 访问V-E, V-F → 连通分量2

输出:
single_products = [SKU-D]
variation_families = [
    [SKU-A, SKU-B, SKU-C],
    [SKU-E, SKU-F]
]
```

**优势**:
- 自动处理任意复杂的关联关系
- 无需预定义家族规则
- 性能高效（线性时间）

---

### 8.2 字段映射算法

**两轮映射策略**:

```python
# 第一轮: 处理非引用字段
for field_name, rule in mapping_config.items():
    if rule['source_type'] != 'field_reference':
        mapped_data[field_name] = map_field(rule)

# 第二轮: 处理field_reference
for field_name, rule in mapping_config.items():
    if rule['source_type'] == 'field_reference':
        referenced_field = rule['field']
        if referenced_field in mapped_data:
            mapped_data[field_name] = mapped_data[referenced_field]
```

**原因**: 
- `field_reference`依赖其他字段已映射
- 两轮确保依赖关系正确

---

### 8.3 标题泛化算法

**正则表达式**:
```python
import re

def generalize_parent_title(title: str) -> str:
    # 移除末尾的 "- 单词" 模式
    generalized = re.sub(r'\s*-\s*\w+$', '', title, flags=re.IGNORECASE)
    return generalized
```

**示例**:
```
"Modern Bathroom Vanity - White" → "Modern Bathroom Vanity"
"24 Inch Cabinet - Black"        → "24 Inch Cabinet"
"Vanity Set - Gray/Wood"         → "Vanity Set - Gray/Wood" (不移除，因有/)
```

**边界情况**:
- 标题中有多个 "-": 只移除最后一个
- 没有 "-": 保持原样
- "-" 后有多个单词: 只移除单个单词的情况

---

### 8.4 Excel表头解析

**处理重复列名**:
```python
header_map = defaultdict(list)

for col_idx in range(1, max_column + 1):
    header_value = cell(row=4, column=col_idx).value
    if header_value:
        header_map[header_value].append(col_idx)

# 结果:
# {
#     'Bullet Point': [15, 16, 17, 18, 19],  # 5列
#     'Other Image URL': [25, 26, 27, 28, 29, 30, 31, 32], # 8列
#     'SKU': [1],  # 单列
#     ...
# }
```

**填充策略**:
```python
if isinstance(value, list):
    # 列表值 → 填充多列
    for i, item in enumerate(value):
        if i < len(col_indices):
            cell(row, col_indices[i]).value = item
else:
    # 单值 → 填充第一列
    cell(row, col_indices[0]).value = value
```

---

## 9. 错误处理机制

### 9.1 异常捕获层级

```
ProductListingService.generate_listings_by_category()
├── try-except 捕获所有异常
│   ├── 数据库异常 → rollback()
│   ├── 文件异常 → 记录日志
│   └── 其他异常 → 记录日志
└── 返回统一格式的结果字典

子方法
├── _process_single_products()
│   └── 单个SKU失败 → 记录警告，继续处理其他SKU
├── _process_variations()
│   └── 单个家族失败 → 记录错误，继续处理其他家族
└── ProductDataRepository.get_full_product_data()
    └── SKU无数据 → 返回空字典
```

### 9.2 常见异常及处理

| 异常类型 | 场景 | 处理方式 | 用户反馈 |
|----------|------|----------|----------|
| **FileNotFoundError** | 模板文件不存在 | 抛出异常 | "找不到品类XXX的模板文件" |
| **ValueError** | 空数据行 | 返回失败结果 | "没有生成任何数据行" |
| **DatabaseError** | SQL执行失败 | rollback() | "数据库查询失败：XXX" |
| **JSONDecodeError** | JSONB解析失败 | 使用默认值 | 记录警告日志 |
| **KeyError** | 缺少必需字段 | 跳过该SKU | 记录警告日志 |

### 9.3 数据验证

**关键验证点**:

```python
# 1. SKU数据完整性
if not product_data:
    logger.warning(f"跳过SKU {meow_sku}: 无数据")
    continue

# 2. 模板规则存在性
if not template_rules:
    return {'success': False, 'message': '品类没有模板规则'}

# 3. 数据行非空
if not all_rows:
    return {'success': False, 'message': '没有生成任何数据行'}

# 4. Excel文件生成成功
if not os.path.exists(excel_file):
    raise FileNotFoundError("Excel文件生成失败")
```

### 9.4 日志级别

```python
logger.info("✅ 正常流程信息")
logger.warning("⚠️  非致命问题，可继续")
logger.error("❌ 错误，但已处理")
logger.exception("❌ 异常，需记录堆栈")
logger.debug("🔍 调试信息")
```

---

## 10. 扩展性说明

### 10.1 新增品类支持

**步骤**:
1. **解析模板**: 使用功能3.2解析Amazon模板文件
2. **配置映射**: 更新`category_mapping.json`（如需）
3. **准备模板**: 将`.xlsm`文件放入`template_files/`
4. **测试**: 生成测试数据验证

**示例**:
```bash
# 1. 解析模板
python main.py
选择: 3.2
输入模板路径: /path/to/DINING_TABLE.xlsm
输入品类名称: DINING_TABLE

# 2. 准备模板文件
cp DINING_TABLE.xlsm template_files/

# 3. 生成发品文件
python main.py
选择: 1.8
选择品类: DINING_TABLE
```

### 10.2 新增映射类型

**在`DataMappingHelper`中添加**:

```python
# 1. 定义新类型
elif source_type == "custom_calculator":
    return self._custom_calculation(rule, product_data)

# 2. 实现方法
def _custom_calculation(self, rule, product_data):
    """自定义计算逻辑"""
    formula = rule.get("formula")
    # 实现计算
    return result
```

### 10.3 支持增补变体

**当前限制**: 每次生成全新家族

**未来扩展**:
```python
def supplement_variation_family(self, parent_sku: str, new_child_skus: List[str]):
    """
    为已有家族增补新子SKU
    
    步骤:
    1. 查询已有家族详情
    2. 只生成新子SKU的行
    3. 不生成父体行
    4. 保持父SKU一致
    """
    # 查询已有家族
    family_details = self.listing_log_repo.get_family_details_by_parent(parent_sku)
    
    # 生成新子体行
    new_rows = []
    for child_sku in new_child_skus:
        row = generate_child_row(child_sku, parent_sku)
        new_rows.append(row)
    
    return new_rows
```

### 10.4 支持更新模式

**当前**: 仅支持创建（Create or Replace）

**扩展**: 支持部分更新
```python
def update_listings(self, update_type: str):
    """
    update_type:
    - 'price_only': 仅更新价格
    - 'inventory_only': 仅更新库存
    - 'description': 更新描述信息
    """
    if update_type == 'price_only':
        # 只填充SKU、Price列
        minimal_fields = ['SKU', 'Standard Price']
        ...
```

### 10.5 性能优化建议

**当前瓶颈**:
1. **逐SKU查询**: `get_full_product_data()`每次查询一个SKU
2. **Excel写入**: 逐行写入可能较慢

**优化方案**:
```python
# 1. 批量查询
def get_bulk_product_data(self, meow_skus: List[str]) -> Dict[str, Dict]:
    """一次查询获取所有SKU数据"""
    query = text("""
        SELECT m.meow_sku, ... 
        FROM meow_sku_map m
        WHERE m.meow_sku = ANY(:sku_list)
    """)
    results = self.db.execute(query, {"sku_list": meow_skus}).fetchall()
    return {row['meow_sku']: dict(row) for row in results}

# 2. 批量写入Excel
def batch_write_cells(worksheet, data_rows):
    """批量写入，减少I/O"""
    for row_idx, row_data in enumerate(data_rows):
        # 批量构建cell对象
        ...
```

### 10.6 监控与告警

**建议指标**:
- **处理时长**: 超过5分钟告警
- **失败率**: 超过10%告警
- **生成行数**: 异常波动告警
- **模板缺失**: 立即告警

**实现**:
```python
import time

start_time = time.time()

# ... 处理逻辑 ...

elapsed_time = time.time() - start_time

if elapsed_time > 300:  # 5分钟
    logger.warning(f"⚠️  处理时长异常: {elapsed_time}秒")
    # 发送告警

if len(all_rows) < 5 and len(pending_skus) > 20:
    logger.warning(f"⚠️  生成行数异常: {len(all_rows)}/{len(pending_skus)}")
    # 发送告警
```

---

## 附录

### A. 完整调用链

```
main.py: handle_generate_listing()
    ↓
ProductListingService.generate_listings_by_category(category_name)
    ↓
    ├─→ ProductListingRepository.get_pending_listing_skus()
    │       ↓ SQL多表联查
    │       └─→ 返回 meow_sku列表
    │
    ├─→ ProductListingRepository.get_sku_to_category_mapping(meow_skus)
    │       ↓ SQL联查
    │       └─→ 返回 [(meow_sku, category), ...]
    │
    ├─→ 过滤指定品类
    │
    ├─→ ProductListingRepository.get_variation_data(pending_skus)
    │       ↓ SQL查询associateProductList
    │       └─→ 返回 [(meow_sku, vendor_sku, [assoc_list]), ...]
    │
    ├─→ VariationHelper.find_variation_families(variation_data)
    │       ↓ 图论DFS
    │       └─→ 返回 (single_skus, variation_families)
    │
    ├─→ AmzTemplateRepository.find_template_by_category(category_name)
    │       ↓ SQL查询amazon_cat_templates
    │       └─→ 返回 template_rules字典
    │
    ├─→ _process_single_products(single_skus, template_rules)
    │       ↓
    │       ├─→ ProductDataRepository.get_full_product_data(meow_sku) × N
    │       │       ↓ SQL 10+表联查
    │       │       └─→ 返回 product_data字典
    │       │
    │       ├─→ DataMappingHelper.apply_mapping(product_data, template_rules)
    │       │       ↓ 根据amz_mapping.json映射
    │       │       └─→ 返回 mapped_data字典
    │       │
    │       └─→ 返回 single_rows列表
    │
    ├─→ _process_variations(variation_families, template_rules)
    │       ↓
    │       ├─→ _process_single_family(family_skus, template_rules) × N
    │       │       ↓
    │       │       ├─→ 生成父SKU
    │       │       │
    │       │       ├─→ ProductDataRepository.get_full_product_data(first_child)
    │       │       │   → DataMappingHelper.apply_mapping()
    │       │       │   → VariationHelper.generalize_parent_title()
    │       │       │   → 生成父体行
    │       │       │
    │       │       ├─→ 循环处理所有子SKU:
    │       │       │   ProductDataRepository.get_full_product_data(child_sku)
    │       │       │   → DataMappingHelper.apply_mapping()
    │       │       │   → 生成子体行
    │       │       │
    │       │       └─→ 返回 (family_rows, family_logs)
    │       │
    │       └─→ 返回 (variation_rows, variation_logs)
    │
    ├─→ 合并 all_rows = single_rows + variation_rows
    │
    ├─→ ExcelGenerator.generate_excel(all_rows, category_name, batch_id)
    │       ↓
    │       ├─→ 加载模板文件 (CABINET.xlsm)
    │       ├─→ 解析表头 (_parse_header)
    │       ├─→ 填充数据 (_fill_data)
    │       └─→ 保存文件到output/
    │
    ├─→ AmzListingLogRepository.bulk_insert_log(all_logs)
    │       ↓ SQL INSERT with ON CONFLICT
    │       └─→ 插入到amz_listing_log表
    │
    └─→ 返回 result字典
```

### B. 数据库Schema参考

```sql
-- meow_sku_map
CREATE TABLE meow_sku_map (
    meow_sku VARCHAR(100) PRIMARY KEY,
    vendor_sku VARCHAR(100) NOT NULL,
    vendor_source VARCHAR(50) NOT NULL
);

-- ds_api_product_details
CREATE TABLE ds_api_product_details (
    id SERIAL PRIMARY KEY,
    sku_id VARCHAR(100) NOT NULL,
    product_name TEXT,
    product_description TEXT,
    selling_point_1 TEXT,
    selling_point_2 TEXT,
    selling_point_3 TEXT,
    selling_point_4 TEXT,
    selling_point_5 TEXT
);

-- giga_product_sync_records
CREATE TABLE giga_product_sync_records (
    id SERIAL PRIMARY KEY,
    giga_sku VARCHAR(100) NOT NULL,
    category_code VARCHAR(100),
    raw_data JSONB,
    is_oversize BOOLEAN DEFAULT FALSE
);

-- supplier_categories_map
CREATE TABLE supplier_categories_map (
    id SERIAL PRIMARY KEY,
    supplier_platform VARCHAR(50) NOT NULL,
    supplier_category_code VARCHAR(100) NOT NULL,
    standard_category_name VARCHAR(100),
    supplier_category_name VARCHAR(255),
    UNIQUE(supplier_platform, supplier_category_code)
);

-- product_final_prices
CREATE TABLE product_final_prices (
    meow_sku VARCHAR(100) PRIMARY KEY,
    final_price DECIMAL(10, 2)
);

-- giga_inventory
CREATE TABLE giga_inventory (
    giga_sku VARCHAR(100) PRIMARY KEY,
    quantity INT DEFAULT 0,
    buyer_qty INT DEFAULT 0
);

-- amazon_cat_templates
CREATE TABLE amazon_cat_templates (
    id SERIAL PRIMARY KEY,
    category VARCHAR(100) NOT NULL,
    template_name VARCHAR(255),
    fields JSONB,
    field_definitions JSONB,
    valid_values JSONB,
    variation_mapping JSONB,
    priority_themes JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- amz_listing_log
CREATE TABLE amz_listing_log (
    id SERIAL PRIMARY KEY,
    meow_sku VARCHAR(100) UNIQUE NOT NULL,
    parent_sku VARCHAR(100),
    variation_attributes JSONB,
    listing_batch_id UUID,
    variation_theme VARCHAR(50),
    status VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

### C. 配置文件模板

**amz_mapping.json示例**:
```json
{
    "mappings": {
        "SKU": {
            "source_type": "direct",
            "value": "meow_sku"
        },
        "Product Type": {
            "source_type": "db_field",
            "field": "category_name"
        },
        "Item Name": {
            "source_type": "db_field",
            "field": "product_name"
        },
        "Bullet Point": {
            "source_type": "db_field_multiple",
            "fields": [
                "selling_point_1",
                "selling_point_2",
                "selling_point_3",
                "selling_point_4",
                "selling_point_5"
            ]
        },
        "Main Image URL": {
            "source_type": "jsonb",
            "json_path": "imageList.0"
        },
        "Standard Price": {
            "source_type": "db_field",
            "field": "final_price"
        }
    }
}
```

---

## 总结

本文档详细阐述了 **1.8 生成亚马逊发品文件模块** 的完整业务逻辑和数据流转过程。

**核心要点**:
1. **11步流程**: 从筛选SKU到生成Excel文件
2. **图论算法**: 使用DFS自动识别变体家族
3. **灵活映射**: 支持12种字段映射类型
4. **数据完整**: 关联10+张表获取完整商品数据
5. **可扩展性**: 支持新增品类、映射类型、更新模式

**适用场景**:
- 新品批量发布
- 分品类管理
- 变体家族构建

**注意事项**:
- 必须先配置品类模板
- SKU必须有完整数据
- 变体关联依赖Giga API准确性

通过本文档，开发者可以：
- ✅ 理解模块的完整业务逻辑
- ✅ 掌握数据流转和表关系
- ✅ 了解核心算法原理
- ✅ 进行功能扩展和优化
- ✅ 排查问题和调试

---

**文档维护**:
- 随代码更新及时同步
- 新增品类时更新配置说明
- 性能优化后更新相关章节