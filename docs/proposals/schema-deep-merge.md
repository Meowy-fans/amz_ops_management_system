# 方案提案：Amazon Schema 深合并（S1）

- **状态**：`Review`
- **日期**：2026-06-25
- **范围分级**：轻量改动（单一核心方法 + 测试 + YAML 重生成），走简化七阶段
- **来源**：`docs/proposals/e2e-issues-summary.md` 问题 #5（frame/seat/maximum_weight_recommendation 的 shape 与 Amazon Schema 不匹配）

---

## 1. 背景与问题

### 1.1 数据流

属性 `shape` 的推断链路：

```
Amazon schema(JSON)
  └─ AmazonSchemaService._merged_properties(schema)   # properties + allOf 合并成一张扁平 props 表
       └─ AttributeRuleGenerator.generate(): properties.get(name)   # 取"合并后定义"
            └─ _shape(prop_schema)                                  # 据 items.properties 推断 shape
                 └─ 写进 <category>.yaml: <attr>.shape
```

整条链路对一个属性的判断，完全取决于 `_merged_properties` 产出的"合并后定义"。

### 1.2 根因：浅合并被条件块整键覆盖

```python
# src/services/amazon_schema_service.py（现状）
@classmethod
def _merged_properties(cls, schema):
    props = dict(schema.get("properties", {}) or {})
    for part in schema.get("allOf", []) or []:
        props.update(part.get("properties", {}) or {})
        for key in ("then", "else"):
            props.update((part.get(key) or {}).get("properties", {}) or {})
    return props
```

`dict.update` 是**整键替换**。Amazon 在 `allOf[].then/else` 里对属性做**部分/约束式再声明**（只为表达"某条件下某子字段必填"），这些残缺补丁会把 root 的完整结构整体冲掉。

### 1.3 实测 case：CHAIR.`frame`

**root `properties.frame`（完整）**

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "required": [],
    "properties": { "color": { ... }, "material": { ... }, "marketplace_id": { ... } }
  }
}
```

**`allOf[21].then.properties.frame`（约束补丁，残缺）** —— 语义：子体 SKU 场景下 `frame.color` 必填：

```json
{ "items": { "required": ["color"] } }
```

**合并后**：`props["frame"]` 被替换为 `{"items": {"required": ["color"]}}`，`items.properties`（color/material）全部丢失。

**`_shape` 拿到残骸** → `items.properties` 为空 → 一路回退到 `return "value"`。

于是 `frame` 被误判为 `shape: value, transform: text` → 产出 `[{"value": "Solid Wood"}]` → Amazon 返回 `90220: 'Frame Material' is required but missing`。

**对照组**：`maximum_weight_recommendation` 无 allOf 叠加层，root 的 `items.properties = {unit, value}` 原样存活 → `_shape` 正确返回 `measure`。这反证：问题不在 `_shape` 不会识别复杂 shape，而在**合并阶段结构被条件补丁冲掉**。`seat`（allOf[45/46].then 同样是空壳）同病。

---

## 2. 技术预研结论（实测数据）

对线上缓存的**全部 17 个品类、2422 个属性**，同时跑「当前浅合并」与「深合并原型」，逐属性对比 `_shape` 结果：

```
SUMMARY:  unchanged=2198   fixes(升级)=224   regressions(降级)=0
TRANSITION:  value -> object : 201
             value -> list_value : 23
```

- **回归 = 0**：深合并从不把当前正确的 shape 改坏，全部变化均为单向"升级"（被冲烂的结构恢复成真实结构）。无 `object/measure -> value` 降级。
- **业务组件属性普遍受益**（非 CHAIR 个例）：`frame`×9 品类、`base`×6、`top`×5、`upholstery`×4、`seat`×3，以及 `arm/back/leg/handle/grip/lens/furniture_leg/headboard/...`。
- **系统/结构属性**（`purchasable_offer/fulfillment_availability/child_parent_sku_relationship/ghs/hazmat/battery/...`）虽也升级，但本就不进业务 YAML，shape 变化惰性无副作用。

预研脚本应固化为回归测试（见 §5.2）。

---

## 3. 方案设计

### 3.1 核心改动

将 `_merged_properties` 的浅 `update` 改为递归深合并：**条件块携带的是约束补丁，必须"合并进"root 定义，而非"整键替换"**。

### 3.2 `deep_merge(base, overlay)` 契约

| 情形 | 规则 |
|------|------|
| 两边都是 dict | 逐键递归合并 |
| 同名键，两边都是 dict | 递归 `deep_merge` |
| 同名键属于并集白名单（`required`）且两边都是 list | 取并集（去重保序） |
| 同名键为标量 / 非白名单 list（如 `enum`/`examples`） | overlay 显式给值才覆盖；若 base 是 dict 而 overlay 不是，保留 base（不被残缺值冲烂） |
| overlay 不含某键 | **保留 base 的值，绝不因 overlay 缺失而清空**（本 bug 的反面，红线） |

并集白名单初始仅含 `required`。**不得**对 `enum`/`examples` 等做盲目 union。

### 3.3 同一 case 走深合并

```
base.frame    = {type: array, items: {type: object, required: [], properties: {color, material, ...}}}
overlay.frame = {items: {required: ["color"]}}

deep_merge →
  frame.type             = "array"               (base 保留)
  frame.items.type       = "object"              (base 保留)
  frame.items.properties = {color, material, ...} (base 保留, overlay 未触碰)   ← 关键
  frame.items.required   = [] ∪ ["color"] = ["color"]  (并集, 约束正确叠加)
```

`_shape` → `items.properties` 非空、无 `value/unit` 键 → 返回 `object`；`_transform` → `passthrough`。`frame` 正确产出 `shape: object`。

### 3.4 then/else 语义（保守策略）

当前实现把 `then` 和 `else` 都无条件合并。严格说二者是 `if` 的互斥分支，全合并会让"必填约束"偏保守（可能把条件必填标成无条件可见）。本方案**第一阶段保持"全合并 + required 并集"的保守策略**，只解决 shape 结构丢失问题；是否按 `if` 求值分支属于后续精细化，不在本方案范围。

---

## 4. 影响范围与边界

### 4.1 受影响代码

| 文件 | 改动 |
|------|------|
| `src/services/amazon_schema_service.py` | `_merged_properties` 改深合并 + 新增 `_deep_merge` 私有方法 |
| `config/amz_listing_data_mapping/api_attribute_rules/*.yaml`（8 个新品类） | 用新逻辑重新生成（dry_run） |

`AttributeRuleGenerator.generate()` 第 165 行直接消费 `_merged_properties`，无需改动即自动生效。

### 4.2 S1 的范围边界（重要）

**S1 只修"shape 标签"，不负责"填什么值"。** frame/seat/base 等升级为 `object/passthrough/manual_review:true` 后，若仍是 `default:null` 且为 required，会变成 `unresolved → blocking`。这是 **fail-closed（更安全）**：把"被静默错填成自由文本"暴露为"需显式提供对象值或排除"。给值/兜底属于 S4（白名单/手工映射）范畴，不在本方案内。

### 4.3 不在本方案范围

- 维度属性归属（S2）、LLM 审核解耦（S3）、safe_default 白名单结构化（S4）。
- `if/then/else` 条件求值。

---

## 5. TDD 测试设计

### 5.1 单元测试（`tests/unit/services/test_amazon_schema_service.py`）

1. `test_deep_merge_preserves_base_properties_when_overlay_partial` — overlay 只含 `items.required` 时，base 的 `items.properties` 完整保留。
2. `test_deep_merge_unions_required_lists` — `required` 取并集去重。
3. `test_deep_merge_does_not_union_enum` — `enum` 不做并集，按覆盖语义处理。
4. `test_merged_properties_frame_resolves_to_object` — 用 CHAIR.frame 结构夹具，断言合并后 `_shape` 得 `object`。
5. `test_merged_properties_measure_unaffected` — 无 allOf 叠加的 measure 属性合并后仍为 `measure`（防回归）。

### 5.2 回归 golden 测试（`tests/unit/services/test_schema_merge_regression.py`）

将 §2 预研脚本固化：对所有缓存品类 schema 夹具，断言"深合并相对浅合并**只升级不降级**（regressions == 0）"。该测试是防止未来 schema 刷新或合并逻辑改动引入静默回归的护栏。

> 夹具来源：从线上缓存导出各品类 `schema_json` 存入 `tests/fixtures/amazon_schemas/`（脱敏，仅结构）。

### 5.3 命名遵循 `test_<功能>_<场景>_<预期>`。

---

## 6. 任务拆解

| TASK | 内容 | DoD |
|------|------|-----|
| T1 | 实现 `_deep_merge` 并改造 `_merged_properties` | 单测 §5.1 全绿 |
| T2 | 导出品类 schema 夹具 + 编写 golden 回归测试 §5.2 | regressions==0 断言通过 |
| T3 | 重新生成 8 个新品类 YAML（dry_run），diff 审查 shape 升级项 | frame/seat 等变为 object，无降级 |
| T4 | 全量 `pytest` + `git diff --check` | 全绿、无 EOF/空白告警 |
| T5 | 更新 `STATUS.md` / `memory/2026-06-25.md` | 验收证据回填 |

---

## 7. 验收标准

1. `AmazonSchemaService._merged_properties` 对 frame/seat 产出含完整 `items.properties` 的合并定义。
2. 重新生成的 `chair.yaml` 中 `frame`、`seat` 的 `shape` 为 `object`，`maximum_weight_recommendation` 保持 `measure`。
3. golden 回归测试通过：17 品类 2422 属性，深合并相对浅合并 **0 降级**。
4. 全量单测通过；新增/修改逻辑单测覆盖。
5. 8 个品类 YAML 重新生成，diff 仅含预期的 shape 升级项，无其他非预期变化。

---

## 8. 回滚预案

- 改动集中于单一纯函数 `_merged_properties`，无 DB schema 变更、无接口契约变更。
- 回滚 = 还原该方法为浅 `update` 版本并重生成 YAML；无数据迁移风险。

---

## 9. 后续衔接

S1 完成后，frame/seat/base 等被正确标为 `object`，为 S4（结构化 safe_default / 手工对象映射）提供准确的 shape 前提；维度属性归属（S2）与 LLM 审核解耦（S3）独立推进。
