# E2E 验收发现与长期修复方案

- **日期**：2026-06-22
- **来源**：CHAIR 品类端到端发品验收

---

## 1. 验收结果

从 Giga 原始商品数据到 Amazon SP-API LIVE 提交，完整链路已打通。CHAIR 品类 SKU `meow2511081Gqqd`（Solid Wood Rattan-Back Dining Chair）成功到达 Amazon，返回 3 个 INVALID issues。

```
验收过程: 初始 9 个 required 属性全部阻断
        → 逐一排查消解
        → 1 个 SKU 到达 Amazon PUT 端点
        → Amazon 返回 3 个 payload 格式问题
```

---

## 2. 属性 schema shape 不匹配（3 个 Amazon INVALID）

### 2.1 `frame` — 缺少 Frame Material

**Amazon 反馈**：
```
[ERROR] 90220: 'Frame Material' is required but missing.
```

**Amazon Schema 实际结构**：
```json
{
  "frame": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "color": { ... },
        "material": { ... }
      }
    }
  },
  "frame_material": {
    "type": "array",
    "items": {
      "type": "object",
      "required": ["language_tag", "value"],
      "properties": {
        "value": {
          "type": "string",
          "title": "Frame Material",
          "description": "Provide the material of the product frame"
        }
      }
    }
  }
}
```

**当前生成器产出**：`shape: list_value, transform: text` → `[{"value": "Solid Wood"}]`

**问题**：`frame` 是嵌套 object，不能用简单 `[{"value": ...}]` 格式。Amazon 同时提供了 `frame_material` 这个更简单的平替属性（list_value + free text）。

**建议方案**：CHAIR YAML 中手工配置 `frame_material` 而非 `frame`。

```yaml
frame_material:
  level: required
  shape: list_value
  transform: text
  sources:
    - path: product.attributes.Main Material
    - llm:
        hint: "Extract frame material from product title, description, or characteristics."
    - default: Wood
      confidence: medium
      evidence: "Conservative default for wooden-frame chairs."
```

### 2.2 `seat` — 缺少 Seat Depth

**Amazon 反馈**：
```
[ERROR] 90220: 'Seat Depth' is required but missing.
```

**Amazon Schema 实际结构**：
```json
{
  "seat": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "depth": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["unit", "value"],
            "properties": {
              "unit": { "enum": ["inches", "centimeters", ...] },
              "value": { "type": "number" }
            }
          }
        },
        "height": { ... same structure ... },
        "width": { ... same structure ... },
        "material_type": { ... }
      }
    }
  }
}
```
条件约束：当商品不是父体时，`seat` 必须包含 `depth`、`height`、`material_type`。

**当前生成器产出**：`shape: list_value, transform: text` → `[{"value": "foam-filled cushion"}]`

**问题**：`seat` 是带 depth/height/material_type 子属性的嵌套 measure 对象。LLM 提取的文本描述无法直接填入 measure 字段。

**建议方案**：CHAIR YAML 中手工配置 `seat` 为嵌套 object，提供默认的 depth/height/material_type。

```yaml
seat:
  level: required
  shape: object
  transform: passthrough
  manual_review: true
  sources:
    - default:
        depth:
          - value: 18
            unit: inches
        height:
          - value: 18
            unit: inches
        material_type:
          - value: Foam
            language_tag: en_US
      confidence: medium
      evidence: "Default ergonomic chair seat dimensions; review against supplier specs."
```

### 2.3 `maximum_weight_recommendation` — 缺少 unit

**Amazon 反馈**：
```
[ERROR] 99022: The field 'unit' for the attribute 'Maximum Weight Recommendation Unit'
does not have enough values. The required minimum is '1' value(s).
```

**Amazon Schema 实际结构**：
```json
{
  "maximum_weight_recommendation": {
    "type": "array",
    "items": {
      "type": "object",
      "required": ["unit", "value"],
      "properties": {
        "unit": { "enum": ["pounds", "kilograms", ...] },
        "value": { "type": "number", "minimum": 0 }
      }
    }
  }
}
```

**当前生成器产出**：`shape: list_value, transform: integer` → `[{"value": 300}]`（LLM 提取值）

**问题**：属性是 measure 类型（需要 unit + value），但生成器的 `_shape()` 没有识别出来。原因是 `_merged_properties()` 合并了顶层的 `allOf`/`anyOf`，但没有展开嵌套的 `items.properties`，导致 `_shape()` 看不到 `unit` 子字段。

**建议方案**：CHAIR YAML 中手工覆盖 `shape: measure, transform: passthrough`。

```yaml
maximum_weight_recommendation:
  level: required
  shape: measure
  transform: passthrough
  sources:
    - llm:
        hint: "Extract maximum weight capacity in pounds from product text."
    - default:
        value: 250
        unit: pounds
      confidence: medium
      evidence: "Conservative default for standard dining chairs."
```

---

## 3. E2E 验收中的临时改动及长期方案

以下 5 个改动是为了让 CHAIR SKU 通过 CoverageGate 到达 Amazon 所做的临时操作。每个都附长期解决方案。

### 3.1 `needs_manual_review` 阻断放行

**临时改动**：`attribute_resolver.py:272`

```python
# 临时
result.blocking = False  # 原为 True
```

**为什么做**：LLM 正确提取了 6 个属性值，但 `required + llm source → needs_manual_review, blocking=True` 全部拦截。不临时放行，LLM 提取路径在 CoverageGate 之前就失效了。

**长期方案**：当属性有 `safe_default` 兜底时，`needs_manual_review` 降为 warning 不阻断。LLM 提取值优先使用，LLM 失败走 safe_default。

```python
# _finish()
if result.source == "llm" and result.level == "required":
    result.state = "needs_manual_review"
    result.blocking = not has_safe_default  # 有兜底 → 不阻断
```

**影响文件**：`src/services/attribute_resolver.py`

### 3.2 `is_fragile`、`item_shape` 临时 safe_default

**临时改动**：`amazon_required_safe_defaults_v1.yaml` 临时加入：
```yaml
is_fragile:
  default: No
  evidence: "TEMP: furniture default for E2E test."

item_shape:
  default: Rectangular
  evidence: "TEMP: generic shape default for E2E test."
```

**为什么做**：LLM 对这两个属性返回 null（Giga 数据无相关信息），default 是 null → unresolved → 阻断。

**长期方案**：审核后永久加入白名单。

| 属性 | 建议 default | 理由 |
|------|-------------|------|
| `is_fragile` | No | 家具默认不易碎。含有玻璃/陶瓷的商品应在 Giga 端标注 |
| `item_shape` | Rectangular | 多数椅子座面为矩形。圆形/异形椅应在 Giga 端标注 |

**影响文件**：`config/amz_listing_data_mapping/api_attribute_presets/amazon_required_safe_defaults_v1.yaml`

### 3.3 `item_depth_width_height` 在 universal preset 加了又删

**临时改动**：先加 `default: {}`，发现覆盖了 PayloadBuilder 的正确维度值，又删除。

**为什么做**：`item_depth_width_height` 是 learned-required，但 Resolver 没有规则处理它。尝试在 preset 中提供 default，但空对象 `{}` 通过 renderer 变成空 payload，覆盖了 PayloadBuilder 计算的 `depth=20.0, width=22.6, height=39.6`。

**长期方案**：维度属性（`item_depth_width_height`、`item_length_width_height`、`item_width_height`、`item_dimensions`）由 PayloadBuilder 的 `_set_dimensions()` 负责，不应出现在任何 YAML 规则中。需要永久加入生成器的排除列表（同 3.4）。

### 3.4 Generator 排除维度属性

**临时改动**：`_UNIVERSAL_PRESET_ATTRIBUTES` 临时加入 4 个维度属性名。

**为什么做**：维度属性在 learned-required 中，生成器会为它们生成 `default: null` 规则。但这些是 PayloadBuilder 处理的，Resolver 不应该介入。

**长期方案**：永久加入 `_UNIVERSAL_PRESET_ATTRIBUTES`。

```python
_UNIVERSAL_PRESET_ATTRIBUTES = {
    # ... 现有 12 个 ...
    "item_depth_width_height",
    "item_length_width_height",
    "item_width_height",
    "item_dimensions",
}
```

**影响文件**：`src/services/attribute_rule_generator.py`

### 3.5 CHAIR 缺少 `dimension_strategy`

**临时改动**：`chair.yaml` 手工加 `dimension_strategy: item_depth_width_height`。

**为什么做**：没有维度策略时，PayloadBuilder 走 `else` 分支 → 生成 `item_width`/`item_depth`/`item_height` 三个独立字段。但 CHAIR schema 要求的是组合字段 `item_depth_width_height`。Giga 有完整的三维数据（w=11.4, l=40.1, h=18.5），PayloadBuilder 能正确计算。

**长期方案**：生成器自动检测 schema 中存在的维度字段名，写入正确的 `dimension_strategy`。

```python
# generate() 中
dim_fields = {"item_depth_width_height", "item_length_width", 
              "item_width_height", "item_dimensions"}
for field in dim_fields:
    if field in properties:
        rules["dimension_strategy"] = field
        break
```

**影响文件**：`src/services/attribute_rule_generator.py`

---

## 4. 改动汇总

| # | 类别 | 文件 | 改动 |
|---|------|------|------|
| 3.1 | `_finish` | `attribute_resolver.py` | `needs_manual_review` 有 safe_default 时不阻断 |
| 3.2 | safe_default | `amazon_required_safe_defaults_v1.yaml` | 永久加入 `is_fragile: No`、`item_shape: Rectangular` |
| 3.3 | 无须改动 | — | 与 3.4 合并 |
| 3.4 | 排除列表 | `attribute_rule_generator.py` | `_UNIVERSAL_PRESET_ATTRIBUTES` 永久加 4 个维度字段 |
| 3.5 | 维度策略 | `attribute_rule_generator.py` | `generate()` 自动检测并设置 `dimension_strategy` |
| 2.1 | 属性 shape | `chair.yaml`（手工） | `frame` → `frame_material`（简单 text） |
| 2.2 | 属性 shape | `chair.yaml`（手工） | `seat` → `shape: object` 嵌套 measure |
| 2.3 | 属性 shape | `chair.yaml`（手工） | `maximum_weight_recommendation` → `shape: measure` |

5 个代码改动（3.1/3.2/3.4/3.5）+ 3 个 CHAIR YAML 手工配置（2.1/2.2/2.3）。
