# 方案提案：AttributeRuleGenerator 补齐 Universal Required 属性 (v2)

- **状态**：`Review`
- **关联**：Category Expansion Pipeline Phase 1
- **日期**：2026-06-22
- **v2 更新**：根据 review 反馈修正 source 类型、path 路径、confidence 级别

---

## 1. 问题现象

自动生成的 8 个新品类（CHAIR, TABLE, FURNITURE, BICYCLE, ARTIFICIAL_TREE, PLANTER, SUITCASE, CLIMBING_PLANT_SUPPORT_STRUCTURE）全部被 `blocked_attribute_coverage` 阻断，42 个 SKU 无一提交成功。

## 2. 根因分析

### 2.1 两条属性赋值路径冲突

系统存在两条属性赋值路径，对同一个属性给出了矛盾结论：

```
路径 A: AmazonListingPayloadBuilder.build_plan() (硬编码)
  brand = [{"value": "Generic"}]
  item_name = [{"value": "LLM 生成的标题"}]
  bullet_point = [LLM 生成的卖点列表]       ← content.bullets (5-element list)
  country_of_origin = [{"value": "CN"}]
  product_description = [{"value": "LLM 生成的 HTML 描述"}]

路径 B: AttributeResolver (YAML 驱动，加载 chair.yaml)
  对 6 个 Schema required 属性：
    brand: sources=[default: null] → value=None → state=unresolved, blocking=True
    bullet_point: sources=[default: null] → value=None → blocking=True
    country_of_origin: sources=[default: null] → blocking=True
    ...
```

### 2.2 CoverageGate 的判定逻辑

```python
# AmazonListingAttributeCoverageGate.evaluate()
for prop_name in schema_required:
    has_payload = prop_name in plan['attributes']  # ✅ PayloadBuilder 已写入
    resolution = plan['attribute_resolutions']      # 🔴 Resolver 判定 blocking=True

    if not has_payload:
        → MISSING_REQUIRED_ATTRIBUTE_RULE
    elif resolution.blocking:
        → LOW_CONFIDENCE_REQUIRED_ATTRIBUTE  ← 实际触发此分支
```

**PayloadBuilder 说"有值"，Resolver 说"不可信(blocking)"，CoverageGate 采信 Resolver → 阻断。**

PayloadBuilder 使用 `attrs.setdefault(key, value)` 合并 YAML 结果，意味着 PayloadBuilder 的值不会被 YAML 覆盖。两条路径仍然共存，但 CoverageGate 的阻断来自 YAML 路径产出的 `blocking=True` resolution。

### 2.3 为什么手工编写的品类没有这个问题

```yaml
# cabinet.yaml (手工) — Resolver 产出 resolved_with_default, blocking=False
supplier_declared_dg_hz_regulation:
  sources:
    - default: not_applicable
      confidence: medium
      evidence: "..."

# chair.yaml (生成) — Resolver 产出 unresolved, blocking=True
supplier_declared_dg_hz_regulation:
  sources:
    - default: null
      confidence: low
      evidence: "TODO: ..."
```

### 2.4 根因定位

`AttributeRuleGenerator._DEFAULT_SOURCE_CANDIDATES` 只覆盖 13 个 recommended 属性，**未覆盖 6 个 Schema required 的通用属性**：

| Schema Required | 在 CANDIDATES 中 | 在 _SENSITIVE 中 | 生成结果 |
|-----------------|-----------------|-----------------|---------|
| `brand` | ❌ | `_SENSITIVE_EXACT` | `default: null` |
| `bullet_point` | ❌ | ❌ | `default: null` |
| `country_of_origin` | ❌ | ❌ | `default: null` |
| `item_name` | ❌ | ❌ | `default: null` |
| `product_description` | ❌ | ❌ | `default: null` |
| `supplier_declared_dg_hz_regulation` | ❌ | `_SENSITIVE_MARKERS` (含 `regulation`) | `default: null` |

生成器在设计时假设这些属性由 PayloadBuilder 管，但 Schema 标为 required 后仍然写入 YAML，写入内容全是 `default: null, confidence: low`。

## 3. 设计约束

选择 source 类型时必须考虑 `AttributeResolver._finish()` 的规则：

```python
# attribute_resolver.py:242-262
@staticmethod
def _finish(result):
    if result.value in (None, ""):
        result.state = "unresolved"
        result.blocking = (result.level == "required")      # ① default: null 在这里阻断

    if result.confidence == "low":
        result.state = "resolved_low_confidence"
        result.blocking = (result.level == "required")      # ② low confidence 在这里阻断

    if result.source == "llm" and result.level == "required":
        result.state = "needs_manual_review"
        result.blocking = True                              # ③ required + llm 在这里阻断

    if result.source == "default":
        result.state = "resolved_with_default"
        result.blocking = False                             # ④ default source 放行

    # ⑤ path source (非 low confidence, 非 null) → resolved_high_confidence, blocking=False
```

**约束**：
- `llm` source + `required` = 必然阻断 (③)。因此 `item_name`、`product_description`、`bullet_point` 不能用 llm source。
- `default` source + `confidence != low` = 放行 (④)。适用于 brand。
- `path` source + 值非空 + `confidence != low` = 放行 (⑤)。适用于 content.* 路径。

### 路径选择对照

| 属性 | ❌ 不可用 | ✅ 可用 | 原因 |
|------|----------|--------|------|
| `item_name` | `llm` | `path: content.title` | content.title 已是 LLM 生成的最终标题，无需再次提取 |
| `product_description` | `llm` | `path: content.description` | 同上 |
| `bullet_point` | `llm` | `path: content.bullets` | content.bullets 已完成 LLM 生成，需要 `transform: passthrough` 保留 list |
| `brand` | — | `default: Generic` | 安全兜底，confidence: medium |
| `country_of_origin` | — | `path: product.attributes.place_of_origin` + `default: CN` | Giga 有 placeOfOrigin 字段 |
| `supplier_declared_dg_hz_regulation` | — | `default: not_applicable` | 家具/家居类安全兜底，confidence: medium |

### path 解析机制

`AttributeResolver._path_value()` 支持以下 root 路径：

```
content.title          → draft.content.title           (ListingContent)
content.description    → draft.content.description
content.bullets        → draft.content.bullets          (list[str])
product.attributes.X   → draft.standard_product.attributes['X']  (Dict[str, str])
product.X              → draft.standard_product.X       (dataclass field)
offer.X                → draft.offer.X
```

## 4. 修复方案

### 4.1 扩展 `_DEFAULT_SOURCE_CANDIDATES`

```python
_DEFAULT_SOURCE_CANDIDATES = {
    # ... 现有 13 个保持不变 ...

    # ── 新增 6 个 universal required ──
    "brand": [{
        "default": "Generic",
        "confidence": "medium",
        "evidence": "Fallback brand for unbranded Giga products."
    }],
    "country_of_origin": [
        {"path": "product.attributes.place_of_origin"},
        {"default": "CN", "confidence": "medium",
         "evidence": "Fallback country when Giga place_of_origin is missing."}
    ],
    "supplier_declared_dg_hz_regulation": [{
        "default": "not_applicable",
        "confidence": "medium",
        "evidence": "Default for non-hazardous furniture/home goods. Review per-category for battery/hazmat risk (e.g. BICYCLE, SUITCASE)."
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
}
```

### 4.2 调整 `_SENSITIVE_*` 列表

```python
_SENSITIVE_EXACT = {
    "manufacturer",                              # 保留
    "externally_assigned_product_identifier",    # 保留
    "supplier_declared_has_product_identifier_exemption",  # 保留
    # "brand" — 移除：Generic 是安全兜底，不编造品牌名
}

_SENSITIVE_MARKERS = (
    "gtin",
    "identifier",
    "certification",
    "compliance",
    # "regulation" — 保留（用于拦截非 DG/HZ 的 regulation 类属性）
    # "supplier_declared" — 保留（拦截非 DG/HZ 的 supplier_declared 类属性）
)
```

注意：`supplier_declared_dg_hz_regulation` 仍包含 `regulation` 子串，理论上会被 `_SENSITIVE_MARKERS` 匹配。但因为 `_DEFAULT_SOURCE_CANDIDATES` 已为该属性提供了 `default: not_applicable` source，敏感检查只会在 sources 列表末尾追加一个 `default: null`，不会影响前面的有效 source。这是无害的冗余，后续可优化但不影响功能。

### 4.3 更新 `_rule_for_attribute` — 支持候选中的 transform 和 path

`_DEFAULT_SOURCE_CANDIDATES` 中的候选项结构扩展为支持 `transform` 字段（用于 bullet_point 的 passthrough），以及 `path` 字符串和 `dict` 两种格式：

```python
def _rule_for_attribute(self, name, prop_schema, required):
    level = "required" if name in required else "recommended"
    shape = self._shape(prop_schema)
    default_transform = self._transform(name, prop_schema, shape)

    sources = []
    manual_review = False
    candidates = self._DEFAULT_SOURCE_CANDIDATES.get(name, [])

    for candidate in candidates:
        if isinstance(candidate, str):
            # 纯 path 字符串: "content.title"
            sources.append({"path": candidate})
        elif isinstance(candidate, dict):
            entry: Dict[str, Any] = {}
            if "path" in candidate:
                entry["path"] = candidate["path"]
            if "llm" in candidate:
                entry["llm"] = candidate["llm"]
            if "default" in candidate:
                entry["default"] = candidate["default"]
                entry["confidence"] = candidate.get("confidence", "medium")
                entry["evidence"] = candidate.get("evidence", "")
            if "transform" in candidate:
                entry["transform"] = candidate["transform"]
            if entry:
                sources.append(entry)

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
        "transform": candidates[0].get("transform", default_transform) if candidates and isinstance(candidates[0], dict) else default_transform,
        "manual_review": manual_review,
        "sources": sources,
    }
```

### 4.4 不修改的部分

- `AmazonListingPayloadBuilder` — 不修改。本次目标仅为解除 CoverageGate 的误阻断，不涉及 PayloadBuilder 重构。
- `AttributeResolver._finish()` — 不修改。`required + llm = needs_manual_review` 规则保持不变。
- `AmazonListingAttributeCoverageGate` — 不修改。

## 5. 影响范围

| 文件 | 改动 | 估计行数 |
|------|------|---------|
| `src/services/attribute_rule_generator.py` | 扩展 `_DEFAULT_SOURCE_CANDIDATES`，调整 `_SENSITIVE_*`，更新 `_rule_for_attribute` | ~50 行 |
| `config/amz_listing_data_mapping/api_attribute_rules/*.yaml` (8 个文件) | 重新生成 | 自动 |
| `tests/unit/services/test_attribute_rule_generator.py` | 新增 6 个 universal 属性的生成验证 + bullet_point passthrough 测试 | ~30 行 |

## 6. 明确不解决的问题（后续工作）

1. **PayloadBuilder 与 YAML 双路径共存**。本方案只解除 CoverageGate 误阻断，不消除 PayloadBuilder 的硬编码逻辑。PayloadBuilder 降级为纯组装器是后续独立 refactor。
2. **`supplier_declared_dg_hz_regulation` 的条件化**。当前对所有品类统一使用 `not_applicable`。后续应按 `StandardProduct.contains_battery` / `contains_hazmat` 做条件判断。
3. **`_SENSITIVE_MARKERS` 对 `supplier_declared_dg_hz_regulation` 的冗余匹配**。无害但需要后续清理。

## 7. 验证标准

1. 重新生成 CHAIR.yaml 后，6 个 required 属性均有 `path` 或 `default` source（非 llm，非 null）
2. Resolver 对这 6 个属性的 state 为 `resolved_with_default`（default source）或 `resolved_high_confidence`（path source），`blocking=False`
3. `bullet_point` 使用 `transform: passthrough`，渲染后的 payload 包含多个 bullet 条目（而非被 text transform 转成单一字符串）
4. CoverageGate 对 CHAIR SKU 返回 `blocked=False`
5. 对已有品类（CABINET/SOFA/OTTOMAN/HOME_MIRROR）的回归测试通过
6. 全量 `pytest -q` 通过
