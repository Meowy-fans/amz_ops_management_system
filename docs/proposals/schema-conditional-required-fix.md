# 方案提案：Schema 条件 Required 提取 + Object 属性平替策略

- **状态**：`Review`
- **日期**：2026-06-25
- **关联**：E2E Case 5 — `frame`/`seat`/`max_weight` shape 不匹配

---

## 1. 问题

以 CHAIR 的 `frame` 属性为例。当前系统行为：

1. `frame` 被 CoverageGate 标记为 required
2. Generator 看到 `frame` schema 是嵌套 object → `shape=object` → `manual_review=True` → `default: null`
3. Resolver 无值产出 → CoverageGate 阻断
4. 解决方案被建议为"手工修改 CHAIR YAML"

**用户要求**：不接受手工 YAML 方案。需要系统性的根因修复。

## 2. 断言与证据

### 2.1 `frame` 在 Amazon Product Type Definitions API 返回的 schema 中

证据：数据库中缓存的 CHAIR schema JSON 原文（`amazon_product_type_schemas` 表）。

```json
{
  "allOf": [{
    "if": { /* 条件：商品不是父体 */ },
    "then": {
      "required": ["frame", "frame_material"],
      "properties": {
        "frame": {
          "items": {
            "required": ["color"],
            "properties": {
              "color": {
                "items": {
                  "properties": {
                    "value": {
                      "enum": ["Beige","Black","Blue","Brown","Gold",
                               "Green","Grey","Multicolor","Orange",
                               "Pink","Purple","Red","Silver","White","Yellow"]
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }]
}
```

`frame` 在 `allOf → then → required` 中。条件是"当商品不是父体时"。

### 2.2 `frame_material` 也在同一条件块中

同一 `then.required` 数组里同时要求了 `frame` 和 `frame_material`。schema 中 `frame_material` 的定义：

```json
{
  "frame_material": {
    "type": "array",
    "items": {
      "type": "object",
      "required": ["language_tag", "value"],
      "properties": {
        "value": {
          "type": "string",
          "title": "Frame Material",
          "examples": ["Cardboard, Metal, Plastic, Wood"],
          "maxLength": 50
        }
      }
    }
  }
}
```

`frame_material.value` 是自由文本（不是 object，不是 enum）。LLM 可以直接提取，Giga 的 `Main Material` 可以直接映射。

### 2.3 当前 `get_expanded_required_properties()` 没有提取到条件块中的 required

验证结果（代码实际执行）：

```
get_required_properties():          6 个 — 只含顶层 required
get_expanded_required_properties(): 6 个 — 也没遍历深层 if/then
get_learned_required_properties():  9 个 — frame, seat, is_fragile, ...
get_coverage_required_properties(): 15 个 — 6 schema + 9 learned
```

`frame` 出现在 coverage-required 中，仅仅因为 learned-required 记住了它。**它本应作为 schema 条件 required 被自动提取**，不需要依赖 learned-required。

### 2.4 `_merged_properties` 深合并已修复，但 required 提取未修复

上一轮提交中对 `_merged_properties` 做了深合并（`_deep_merge_schema_node`），能正确展开 `frame` 的完整属性结构（包含 `color` enum、`material` 等子字段）。但 `_collect_conditional_required_property_names` 和 `get_expanded_required_properties` 仍使用旧的浅遍历逻辑，没有进入 `allOf/if/then` 块提取 required。

---

## 3. 根因

### 层一：深层条件 required 未被 schema 提取

**文件**：`src/services/amazon_schema_service.py`

`_collect_conditional_required_property_names` 当前只遍历 `allOf` 的直接子节点，不进入 `if/then/else` 块。导致 `frame`、`frame_material`、`seat` 等条件 required 属性要从 learned-required 才算数。

**后果**：
- `frame` 靠 learned-required 标记为 required，但 learned-required 只存 name 字符串
- `frame_material` 同一条件块要求，但从未被任何提交触发 feedback → 既不在 schema-required 也不在 learned-required → 完全被忽略
- Generator 只能看到 `frame` = object → 放弃处理

### 层二：object 属性的平替未被利用

即使层一修复后 `frame` 从 schema 正确提取为 required，`frame` 本身仍是 object（`{color, material}`）。Generator 对 object 的处理策略是 `manual_review=True, default: null`。

但 schema 同一条件块里有 `frame_material`——结构更简单（list_value, free text），同样 required，且 Giga 有 `Main Material` 数据可以直接映射。

Generator 没有"在 required object 的同条件块中搜索更简单的平替属性"的能力。

---

## 4. 修复方案

### 4.1 层一：遍历 `allOf/if/then/else` 提取条件 required

**文件**：`src/services/amazon_schema_service.py`

**改法**：`_collect_conditional_required_property_names` 递归进入 `if/then/else` 块：

```python
@classmethod
def _collect_conditional_required_property_names(
    cls,
    schema: Dict[str, Any],
) -> List[str]:
    names: List[str] = []
    for part in schema.get("allOf", []) or []:
        for key in ("then", "else"):
            block = (part.get(key) or {})
            # 当前：只取 block.properties.* 
            # 修复：也取 block.required
            names.extend(cls._collect_direct_required_property_names(block))
            # 递归进入更深的条件块
            names.extend(cls._collect_conditional_required_property_names(block))
        # 递归进入 if 的条件块（if 本身也可能嵌套）
        names.extend(cls._collect_conditional_required_property_names(
            part.get("if") or {}
        ))
    return names
```

**效果**：
- `get_expanded_required_properties('CHAIR')` 返回列表包含 `frame`、`frame_material`、`seat` 等条件 required 属性
- learned-required 不再需要记住这些属性
- Generator 能看到 `frame_material` 也在 required 列表中

### 4.2 层二：Generator 对 required object 搜索平替属性

**文件**：`src/services/attribute_rule_generator.py`

**改法**：当 required 属性是 object/nested_object 时，在 schema properties 中搜索同条件块或语义相关的更简单属性：

```python
def _candidate_attribute_names(self, properties, required):
    names = []
    for name in required:
        if name in properties and name not in names and name not in self._UNIVERSAL_PRESET_ATTRIBUTES:
            prop_schema = properties.get(name, {})
            shape = self._shape(prop_schema)
            if shape in {"object", "nested_object"}:
                # 搜索同条件块的平替属性
                alternatives = self._find_simple_alternatives(name, properties, required)
                names.extend(alternatives)
            else:
                names.append(name)
    # ... continue with DEFAULT_SOURCE_CANDIDATES
    return names

def _find_simple_alternatives(self, name, properties, required):
    """Given 'frame' (object), find 'frame_material' (simple) if both are required."""
    alt_names = []
    name_pattern = name.replace("_", "").lower()
    for req_name in required:
        if req_name == name:
            continue
        req_schema = properties.get(req_name, {})
        req_shape = self._shape(req_schema)
        if req_shape not in {"object", "nested_object"}:
            # Check if this is a related attribute (e.g., frame_material for frame)
            req_pattern = req_name.replace("_", "").lower()
            if name_pattern in req_pattern or req_pattern in name_pattern:
                alt_names.append(req_name)
    return alt_names
```

**效果**：
- CHAIR: `frame`(object) → 搜索 → `frame_material`(simple) 也在 required 中 → 生成 `frame_material` 规则
- `frame_material` 规则自动包含 `path: product.attributes.Main Material` + `llm` + `default`
- 对 `seat` 同理——如果 schema 有 `seat_material` 等更简单的平替，自动选择

### 4.3 补充：对没有平替的 object required

如果 required object 在 schema 中完全没有更简单的平替（例如 `seat` 只有深度/高度/材质子字段，没有 `seat_height` 等独立属性），则回退到当前行为：`manual_review=True, default: null`。

这种情况不做自动处理，因为：
- 嵌套 measure 对象无法用固定 default（每个商品的实际尺寸不同）
- LLM 不能可靠提取 measure 值
- PayloadBuilder 的维度策略是正确路径（Giga 有三维数据）

## 5. 影响范围

| 文件 | 改动 |
|------|------|
| `src/services/amazon_schema_service.py` | `_collect_conditional_required_property_names` 递归进入 `if/then/else` |
| `src/services/attribute_rule_generator.py` | `_candidate_attribute_names` + 新增 `_find_simple_alternatives` |
| `tests/unit/services/test_amazon_schema_service.py` | 验证条件 required 提取 |
| `tests/unit/services/test_attribute_rule_generator.py` | 验证平替选择 |

不涉及：Resolver、CoverageGate、ConfidenceScorer、任何手工 YAML 配置。

## 6. 验证标准

1. `get_expanded_required_properties('CHAIR')` 包含 `frame`、`frame_material`（来自 schema 条件块，非 learned-required）
2. 重新生成 CHAIR.yaml 后，`frame_material` 有完整的 path+llm+default 规则，`frame` 不再出现在 attributes 中
3. Resolver 能为 `frame_material` 产出非 null 值（从 Giga Main Material 或 LLM 提取）
4. `frame_material` 的值能通过 CoverageGate
5. 对已有品类（CABINET/SOFA/OTTOMAN/HOME_MIRROR）回归测试通过
6. 全量 `pytest -q` 通过
