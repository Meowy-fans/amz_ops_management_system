# 方案提案：Generator 对任意 required 属性自动生成 llm + default 链条

- **状态**：`Review`
- **日期**：2026-06-22

---

## 1. 问题

当前 `AttributeRuleGenerator._rule_for_attribute()` 只对 `_DEFAULT_SOURCE_CANDIDATES` 中预配置的 23 个属性生成 path/llm/default 链条。不在候选表中的属性——不管是不是 required——全部产出 `default: null, confidence: low, manual_review: true`，导致 Resolver 判定 `unresolved, blocking=True`，CoverageGate 阻断。

CHAIR 品类 167 个 Schema 属性中，只有 25 个（23 candidates + 12 universal preset）被正确覆盖。`maximum_weight_recommendation` 等 9 个 learned-required 属性不在覆盖范围内，全部阻断。

**具体代码路径**（`attribute_rule_generator.py` line 238-270）：

```python
for candidate in self._DEFAULT_SOURCE_CANDIDATES.get(name, []):
    # name 不在候选表中 → candidates = [] → 不生成任何 source

manual_review = (... or not sources or ...)
# sources 为空 → manual_review = True

if manual_review and not sources:
    sources.append({
        "default": None,       # ← 没有 llm，没有合理的兜底值
        "confidence": "low",
        "evidence": "TODO: ..."
    })
```

## 2. 预期行为

对任意 required 属性（含 schema-required 和 learned-required），生成器应自动产出标准三层 source 链条：

```
path（如有候选映射）→ llm（通用提取）→ default（安全兜底）
```

- 如果有 `_DEFAULT_SOURCE_CANDIDATES` 映射 → 用预配置的 path
- 如果没有 → 跳过 path，直接 llm → default
- llm 使用通用 hint（从商品名、描述、特征中提取属性值）
- default 使用类型感知的安全兜底（integer→1, boolean→No, enum→第一个合法值, text→品类名等）
- object/nested_object 类型的属性保持 manual_review（无法自动生成合理的 default）

示例——对 `maximum_weight_recommendation`（required, integer），生成器应产出：

```yaml
maximum_weight_recommendation:
  level: required
  shape: list_value
  transform: integer
  sources:
    - llm:
        hint: "Extract maximum weight recommendation (in pounds) from product name, description, or characteristics. Return null if not mentioned."
    - default: 250
      confidence: medium
      evidence: "Auto-generated conservative fallback for maximum_weight_recommendation."
```

## 3. 建议修改

### 3.1 `_rule_for_attribute` 末尾逻辑

当前（line 257-277）：

```python
manual_review = (
    (self._is_sensitive(name) and name not in self._SAFE_DEFAULT_ATTRIBUTES)
    or not sources
    or shape in {"object", "nested_object"}
)
if manual_review and not sources:
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

改为：

```python
is_sensitive_attr = (
    self._is_sensitive(name) and name not in self._SAFE_DEFAULT_ATTRIBUTES
)

if not sources and level == "required":
    if shape not in {"object", "nested_object"} and not is_sensitive_attr:
        sources = self._auto_sources(name, shape, default_transform)
        manual_review = False
    else:
        manual_review = True
        sources.append({
            "default": None,
            "confidence": "low",
            "evidence": f"TODO: review source mapping for {name}",
        })
elif not sources:
    manual_review = True
    sources.append({
        "default": None,
        "confidence": "low",
        "evidence": f"TODO: review source mapping for {name}",
    })
else:
    manual_review = is_sensitive_attr or shape in {"object", "nested_object"}

return {
    "level": level,
    "shape": shape,
    "transform": override_transform or default_transform,
    "manual_review": manual_review,
    "sources": sources,
}
```

### 3.2 新增 `_auto_sources` 方法

```python
def _auto_sources(self, name: str, shape: str, transform: str) -> List[Dict[str, Any]]:
    """Generate a generic llm + default chain for an uncovered required attribute."""
    hint = (
        f"Extract {name} from the product title, description, bullet points, "
        f"and characteristics. Return ONLY the value, no explanation. "
        f"Return null if the information is not found."
    )
    default_value = self._auto_default(name, shape, transform)

    return [
        {"llm": {"hint": hint}},
        {
            "default": default_value,
            "confidence": "medium",
            "evidence": f"Auto-generated fallback for {name}.",
        },
    ]

@staticmethod
def _auto_default(name: str, shape: str, transform: str) -> Any:
    """Return a type-aware safe default for an auto-generated attribute rule."""
    if transform == "integer":
        return 1
    if transform in ("boolean", "boolean_yes_no"):
        return "No" if transform == "boolean_yes_no" else False
    if transform == "enum":
        return None  # enum without valid_values context — llm must provide
    if shape == "list_value":
        return "N/A"
    return "N/A"
```

## 4. 约束与边界

### 4.1 仍然保持 manual_review 的情况

以下属性不会被自动覆盖，保持 `default: null, manual_review: true`：

- **object / nested_object**：嵌套结构无法自动生成合理的 default
- **sensitive 属性**：`_SENSITIVE_EXACT` 和 `_SENSITIVE_MARKERS` 中的属性（gtin, identifier, certification, compliance, regulation）
- **recommended 属性**：只有 required 触发自动生成，recommended 保持现状（不阻断发品）

### 4.2 `required + llm` 的 `_finish` 约束仍然生效

`AttributeResolver._finish()` 规定 `required + llm source = needs_manual_review, blocking=True`。但自动生成的链条是 `llm → default`，当 llm 返回 null 时，default 兜底生效，source 为 `default`，`_finish` 走 `resolved_with_default, blocking=False`。只有当 llm 实际返回了值，source 才是 `llm`，此时触发 `needs_manual_review`——这符合预期：LLM 提取的 required 值需要人工审核。

## 5. 影响范围

| 文件 | 改动 |
|------|------|
| `src/services/attribute_rule_generator.py` | `_rule_for_attribute` 末尾逻辑调整 + 新增 `_auto_sources`、`_auto_default` 方法 |
| `config/amz_listing_data_mapping/api_attribute_rules/*.yaml` (8 个文件) | 重新生成 |
| `tests/unit/services/test_attribute_rule_generator.py` | 新增：required 属性自动生成 llm+default 的断言 |

## 6. 效果

修改后，重新生成 CHAIR.yaml，`maximum_weight_recommendation` 等 9 个 learned-required 属性将自动获得 `llm → default` 规则，Resolver 产出 `resolved_with_default`（default 兜底时）或 `needs_manual_review`（LLM 实际提取到值时），CoverageGate 不再因 `default: null` 而误阻断。
