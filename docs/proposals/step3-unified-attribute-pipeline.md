# 方案提案：Step 3 统一属性解析管道

- **状态**：`Review`
- **日期**：2026-06-22

---

## 1. 背景与问题

### 1.1 当前架构

```
Step 1: LLM 生成通用营销内容 (title, description, bullets)
Step 2: PayloadBuilder 硬编码属性值 + 组装 SP-API JSON
Step 3: YAML Resolver + LLM 补齐品类特有属性
```

E2E 验收中出现三个问题：

### 1.2 问题一：Step 2 与 Step 3 业务规则冲突

6 个 Schema required 属性在 Step 2 由 Python 硬编码写入值（`brand = "Generic"`），但 Step 3 的 YAML 规则给出 `default: null, confidence: low`。Resolver 判定 `unresolved, blocking=True`，CoverageGate 采信 Resolver → 42 个 SKU 被 `blocked_attribute_coverage` 阻断。

```
Step 2: attrs["brand"] = [{"value": "Generic"}]   ✅ 有值
Step 3: resolution["brand"] = blocking=True        🔴 不可信
CoverageGate: 看到有值但不可信 → LOW_CONFIDENCE_REQUIRED_ATTRIBUTE → BLOCKED
```

### 1.3 问题二：业务规则嵌入代码，不可扩展

以下规则硬编码在 `payload_builder.py` 中，新增品类不可见、不可改：

```python
# payload_builder.py
attrs["brand"] = "Generic"                    # line 49
attrs["manufacturer"] = "Nova Home Essentials" # line 50
attrs["target_audience_base"] = "Homeowners"   # line 55
country = ... or "China"                       # line 65
```

新增品类时，这些规则对新品类的 YAML 完全透明。YAML 生成器不知道"品牌一律 Generic"，产出了相互矛盾的 `default: null`。

### 1.4 问题三：LLM 属性提取时 Giga 原始信息丢失

Step 3 的 `LLMAttributeExtractor._context()` 传给 LLM 的是 Step 1 LLM 改写过的 title/bullets/description。Giga 供应商的原始特征描述（`characteristics`，3-8 条详细段落）没有传入。

```
传入 LLM:  title (Step 1 改写), bullets (Step 1 改写), description (Step 1 改写)
丢失:      Giga characteristics (供应商原文), raw_name (原始商品名)
```

Step 1 LLM 的任务是"创作营销文案"，可能省略或改写事实细节。例如 SOFA 的 characteristics 包含 "Checkered Fabric Design...fabric and armrest combination..."、"Three-Seater Foam Sofa" 等可用于提取 arm style / back style / seating capacity 的关键信息，但这些可能不在 Step 1 生成的精简 bullets 中。

---

## 2. 目标架构

```
Step 1: LLM 生成通用营销内容 (title, description, bullets)
           │
           ▼
Step 2: 纯结构组装 — 仅负责 SP-API JSON shape 包装
        ❌ 不再决定任何属性的值
           │
           ▼
Step 3: YAML 配置驱动 — 所有属性的唯一取值路径
        ├── path:      从 Draft / Giga 原始数据读取
        ├── llm:       LLM 提取（使用 Giga 原始数据 + Step 1 营销内容）
        └── default:   业务兜底规则（可配置，可扩展）
```

三个原则：
- **所有属性值由 YAML 规则唯一决定**。PayloadBuilder 不再自行写入任何属性。
- **LLM 提取时同时看到 Giga 原始数据和 Step 1 改写结果**。原始数据用于事实提取，改写结果用于理解商品定位。
- **业务兜底规则可配置**。brand = Generic, country → CN 等规则集中在 YAML 候选表中，新增品类自动继承。

---

## 3. 改动项

### 3.1 LLM Context 补充 Giga 原始数据

**文件**：`src/services/llm_attribute_extractor.py`

在 `_context()` 方法中增加三个字段：

```python
@staticmethod
def _context(draft, attribute, config, valid_values):
    content = draft.content
    product = draft.standard_product
    raw = getattr(product, "raw_source_data", {}) or {}

    return {
        "sku": draft.sku,
        "product_type": draft.product_type,
        "attribute": attribute,
        "hint": config.get("hint", ""),
        "enum_locked": bool(config.get("enum_locked")),
        "valid_values": valid_values,
        # Step 1 生成的营销内容（了解商品定位）
        "title": content.title,
        "bullets": list(content.bullets or []),
        "description": content.description,
        # Giga 标准化属性
        "product_attributes": dict(product.attributes or {}),
        # ── 新增：Giga 原始数据（精确提取属性事实）──
        "raw_name": raw.get("name", ""),
        "raw_description": raw.get("description", ""),
        "raw_characteristics": list(raw.get("characteristics") or []),
    }
```

effect：LLM 在判定 `arm` style 时，既能看到 Step 1 的 title "Modern Boneless Couch..."（了解商品定位），也能看到 Giga characteristics 中的 "fabric and armrest combination adds a modern touch"（提取具体 arm 特征）。

context 增加约 1-2KB，LLM token 消耗轻微增加，提取准确率提升抵消成本。

### 3.2 Generator 覆盖全部 Schema required 属性

**文件**：`src/services/attribute_rule_generator.py`

#### 3.2.1 扩展 `_DEFAULT_SOURCE_CANDIDATES`

新增 6 个 universal required 属性的候选规则：

```python
_DEFAULT_SOURCE_CANDIDATES = {
    # ... 现有 13 个不变 (model_name, fabric_type, color, room_type 等) ...

    "brand": [{
        "default": "Generic",
        "confidence": "medium",
        "evidence": "Fallback brand for unbranded Giga products."
    }],
    "manufacturer": [{
        "default": "Nova Home Essentials",
        "confidence": "medium",
        "evidence": "Default manufacturer for Giga-sourced products."
    }],
    "country_of_origin": [
        {"path": "product.attributes.place_of_origin"},
        {"default": "CN", "confidence": "medium",
         "evidence": "Fallback when Giga place_of_origin is missing."}
    ],
    "supplier_declared_dg_hz_regulation": [{
        "default": "not_applicable",
        "confidence": "medium",
        "evidence": "Default for non-hazardous goods. Review per-category for battery/hazmat risk."
    }],
    "item_name": [
        {"path": "content.title"}
    ],
    "product_description": [
        {"path": "content.description"}
    ],
    "bullet_point": [
        {"path": "content.bullets", "transform": "passthrough"}
    ],
    "target_audience_base": [{
        "default": "Homeowners",
        "confidence": "medium",
        "evidence": "Default target audience for home/furniture products."
    }],
    "item_type_keyword": [
        {"path": "content.title", "transform": "text"}
    ],
    "item_type_name": [
        {"path": "content.title", "transform": "text"}
    ],
}
```

#### 3.2.2 调整 `_SENSITIVE_EXACT`

```python
_SENSITIVE_EXACT = {
    "externally_assigned_product_identifier",
    "supplier_declared_has_product_identifier_exemption",
    # "brand" — 移除。"Generic" 是安全兜底，不构成品牌编造。
    # "manufacturer" — 移除。"Nova Home Essentials" 是统一品牌名。
}
```

#### 3.2.3 从 `_SENSITIVE_MARKERS` 移除 `supplier_declared`

```python
_SENSITIVE_MARKERS = (
    "gtin",
    "identifier",
    "certification",
    "compliance",
    # "regulation" — 保留。（防止非 DG/HZ 的 regulation 类属性被自动填充）
    # "supplier_declared" — 移除。（supplier_declared_dg_hz_regulation 已有安全 default）
)
```

注意：`supplier_declared_dg_hz_regulation` 仍包含 `regulation` 子串，理论上仍会被 `_SENSITIVE_MARKERS` 匹配。但 `_DEFAULT_SOURCE_CANDIDATES` 已在 source 列表首位提供 `not_applicable`，敏感检查只会在末尾追加 `default: null`（first-win 顺序下不生效）。这是无害冗余，后续可单独清理但不影响功能。

#### 3.2.4 更新 `_rule_for_attribute` 支持 dict 候选

候选条目当前只支持 string path。扩展支持 dict 格式的 `path`、`default`、`llm`、`transform`：

```python
def _rule_for_attribute(self, name, prop_schema, required):
    level = "required" if name in required else "recommended"
    shape = self._shape(prop_schema)
    default_transform = self._transform(name, prop_schema, shape)

    sources = []
    override_transform = None
    candidates = self._DEFAULT_SOURCE_CANDIDATES.get(name, [])

    for candidate in candidates:
        if isinstance(candidate, str):
            sources.append({"path": candidate})
        elif isinstance(candidate, dict):
            entry = {}
            if "path" in candidate:
                entry["path"] = candidate["path"]
            if "default" in candidate:
                entry["default"] = candidate["default"]
                entry["confidence"] = candidate.get("confidence", "medium")
                entry["evidence"] = candidate.get("evidence", "")
            if "llm" in candidate:
                entry["llm"] = candidate["llm"]
            if "transform" in candidate:
                entry["transform"] = candidate["transform"]
                override_transform = candidate["transform"]
            if entry:
                sources.append(entry)

    manual_review = False
    if not sources:
        manual_review = self._is_sensitive(name) or shape in {"object", "nested_object"}
        if manual_review:
            sources.append({
                "default": None,
                "confidence": "low",
                "evidence": f"TODO: review source mapping for {name}",
            })

    return {
        "level": level,
        "shape": shape,
        "transform": override_transform or default_transform,
        "manual_review": manual_review,
        "sources": sources,
    }
```

### 3.3 PayloadBuilder 移出业务规则

**文件**：`src/services/amazon_listing_payload_builder.py`

#### 3.3.1 移除已迁移到 YAML 的硬编码

以下 4 行从 `build_plan()` 中删除：

```python
# 删除（已由 YAML _DEFAULT_SOURCE_CANDIDATES 覆盖）：
self._set_text(attrs, "brand", "Generic")                     # line 49
self._set_text(attrs, "manufacturer", "Nova Home Essentials")  # line 50
self._set_text(attrs, "target_audience_base", "Homeowners")    # line 55
# line 65 的 country fallback 逻辑保持不变，但 YAML 会优先通过 path 读取
```

保留在 PayloadBuilder 中的（纯结构组装，不属于业务规则）：
- `item_name`, `product_description`, `bullet_point` — 但这些在 YAML 中已有 `path: content.*` 规则，PayloadBuilder 的值会被 YAML `setdefault` 逻辑覆盖（不变）。
- 图片、价格、库存、尺寸、变体关系 — 继续由 PayloadBuilder 处理（纯结构组装）。

#### 3.3.2 setdefault 改为 update

当前：YAML 值不会覆盖 PayloadBuilder 值。

```python
# 改前 (line 311)
for key, value in rendered.items():
    attrs.setdefault(key, value)  # PayloadBuilder 优先
```

改为：

```python
# 改后
for key, value in rendered.items():
    attrs[key] = value  # YAML 规则为权威来源
```

YAML 成为所有属性的唯一权威。PayloadBuilder 只负责那些不涉及属性值的纯结构任务（图片、价格 JSON shape）。

---

## 4. 影响范围

| 文件 | 改动 | 估计行数 |
|------|------|---------|
| `src/services/llm_attribute_extractor.py` | `_context()` 补充 raw_name/raw_description/raw_characteristics | +3 行 |
| `src/services/attribute_rule_generator.py` | 扩展 `_DEFAULT_SOURCE_CANDIDATES`、调整 `_SENSITIVE_*`、更新 `_rule_for_attribute` | ~60 行 |
| `src/services/amazon_listing_payload_builder.py` | 移除 3 行硬编码 + `setdefault` → `update` | ~5 行 |
| `config/amz_listing_data_mapping/api_attribute_rules/*.yaml` (8 个文件) | 重新生成 | 自动 |
| `tests/unit/services/test_llm_attribute_extractor.py` | 验证新 context 字段 | ~15 行 |
| `tests/unit/services/test_attribute_rule_generator.py` | 验证 universal 属性生成 + passthrough | ~30 行 |
| `tests/unit/services/test_amazon_listing_payload_builder.py` | 更新以反映移除的硬编码 | ~10 行 |

不修改：`AttributeResolver`、`AmazonListingAttributeCoverageGate`。

---

## 5. 验证标准

1. `_context()` 包含 `raw_name`、`raw_description`、`raw_characteristics`
2. 重新生成 CHAIR.yaml 后，所有 required 属性均有 `path` 或 `default` source（非 llm，非 null）
3. `bullet_point` 使用 `transform: passthrough`
4. Resolver 对所有 required 属性的 state 为 `resolved_high_confidence` 或 `resolved_with_default`，`blocking=False`
5. CoverageGate 对 CHAIR SKU 返回 `blocked=False`
6. PayloadBuilder 中 `brand`/`manufacturer`/`target_audience_base` 硬编码已移除
7. 对已有品类（CABINET/SOFA/OTTOMAN/HOME_MIRROR）的回归：YAML 新 default 值（brand=Generic, manufacturer=Nova）与 PayloadBuilder 原值一致，不产生差异
8. 全量 `pytest -q` 通过
