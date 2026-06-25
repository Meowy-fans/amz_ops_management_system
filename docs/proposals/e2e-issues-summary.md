# E2E 验收问题总结

- **日期**：2026-06-22
- **品类**：CHAIR
- **结果**：1 个 SKU 到达 Amazon PUT 端点，Amazon 返回 3 个 INVALID

---

## 问题一：`required + llm → needs_manual_review` 阻断 LLM 提取的所有 required 属性

LLM 成功提取了值（如 `frame=Solid Wood`、`number_of_items=2`），但因为 source=llm + level=required，`_finish()` 全部判定 `needs_manual_review, blocking=True`。即使有 `safe_default` 兜底，LLM 提取路径也永远无法自动通过。

**代码位置**：`src/services/attribute_resolver.py:271-273`

---

## 问题二：`is_fragile`、`item_shape` LLM 返回 null，无 safe_default

LLM 因 Giga 数据缺失返回 null，default 也是 null → unresolved → CoverageGate 阻断。

---

## 问题三：维度属性 `item_depth_width_height` 被 Resolver 和 PayloadBuilder 双重处理冲突

- PayloadBuilder 的 `_set_dimensions()` 计算了正确的维度值（如 `depth=20.0, width=22.6, height=39.6`）
- 但 `item_depth_width_height` 在 learned-required 列表中，Generator 为其生成了规则，Resolver 产出的空 resolution 覆盖了 PayloadBuilder 的正确值
- 维度属性不应出现在任何 YAML 规则中

---

## 问题四：新品类缺少 `dimension_strategy`

CHAIR YAML 没有 `dimension_strategy` 配置，PayloadBuilder 无法生成 Amazon 要求的 `item_depth_width_height` 组合字段，只能生成 `item_width`/`item_depth`/`item_height` 独立字段。而 CHAIR schema 要求的是组合字段。

---

## 问题五：3 个属性的 YAML shape 配置与 Amazon Schema 不匹配

Amazon CHAIR schema 要求：

| 属性 | Amazon Schema 实际结构 | 生成器产出 |
|------|----------------------|-----------|
| `frame` | 嵌套 object `{color, material}` 或用 `frame_material`（简单 text） | `shape: list_value` → `[{"value": "Solid Wood"}]` |
| `seat` | 嵌套 measure object `{depth: {value, unit}, height: {value, unit}, material_type}` | `shape: list_value` → `[{"value": "foam-filled..."}]` |
| `maximum_weight_recommendation` | measure 类型 `{value: 300, unit: "pounds"}` | `shape: list_value, transform: integer` → `[{"value": 300}]` 缺 unit |

**根因**：`_merged_properties()` 没有展开嵌套的 `items.properties`，`_shape()` 看不到底层的 `unit`/`value` 字段，无法识别 measure 和 object 类型。

---

## 问题六：Qwen LLM 在处理 list 类型输出时 JSON 结构间歇性损坏

同一 context 连续调用 3 次，约 33% 概率 Qwen 返回非法 JSON——value 数组的元素被 spill 到父级 JSON 对象中。

**详情**：`docs/proposals/llm-json-parse-failure-diagnosis.md`
