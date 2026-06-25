# LLM JSON 解析失败诊断报告

- **日期**：2026-06-22
- **影响**：8 个品类 29 个 SKU 全部 `blocked_attribute_coverage`，LLM 提取路径批量失效

---

## 1. 现象

LLM 开启后批量发品，所有 `required + llm` 属性报"无值"。日志出现 JSON 解析错误：

```
ERROR:infrastructure.llm.clients.qwen_client:JSON解析失败 | provider=qwen model=qwen-plus-latest
ERROR:infrastructure.llm.implementations.direct_llm_service:LLM调用失败 (qwen): 无效JSON响应: Expecting ':' delimiter
```

## 2. 复现

### 2.1 复现方法

对同一 SKU（`meow2511081Gqqd`，Solid Wood Rattan-Back Dining Chair）的 `included_components` 属性，连续调用 LLM 提取 3 次。

### 2.2 复现结果

3 次调用：2 次成功，1 次失败。失败率约 33%。

### 2.3 请求参数

- **Provider**: qwen
- **Model**: `qwen-plus-latest`
- **temperature**: `0.0`
- **result_format**: `message`（非 `json_object`）
- **json_mode**: `True`
- **task_type**: `product_attribute_extraction`

System prompt（来自 PromptManager）:

```
You extract exactly one Amazon listing attribute from supplier product facts.
Return ONLY valid JSON. Do not include explanations.

Strict rules:
1. Do not invent values. If the source text does not clearly support the requested value,
   return {"value": null, "evidence": "", "confidence": "low"}.
2. The evidence field must quote or closely paraphrase the source phrase that supports the value.
3. Confidence may only be "low" or "medium"; never return "high".
4. If enum_locked is true, the value must exactly match one item in valid_values.
5. Never infer brand, identifiers, GTIN, certifications, compliance declarations,
   hazardous goods declarations, or regulatory claims.

Output contract:
{
  "value": "string | number | boolean | object | null",
  "evidence": "short source phrase, empty when value is null",
  "confidence": "low | medium"
}
```

User prompt（部分，完整 context 约 3KB，含 title, bullets, description HTML, product_attributes, raw_name, raw_characteristics 等）:

```
Extract only the requested attribute from the supplied product facts.
Rules:
- Do not invent values.
- Use null when the text does not explicitly support a value.
- Evidence must quote or closely paraphrase the source fact.
- If enum_locked is true, value must be one of valid_values exactly.

CONTEXT:
{"sku": "meow2511081Gqqd", "product_type": "CHAIR", "attribute": "included_components",
 "hint": "Extract included components from product facts.", "enum_locked": false,
 "valid_values": [],
 "title": "Solid Wood Rattan Back Dining Chair - Beige Linen Cushion, S-Springs Support",
 "bullets": [...5 items...],
 "description": "<b>Experience Lasting Comfort...</b>...",
 "product_attributes": {"Filler": "Foam", "Main Material": "Linen", "Seating Quantity": "Set of 2", ...},
 "raw_characteristics": ["Solid Wood Construction - Made of full solid wood...", ...5 items...]}

OUTPUT_CONTRACT:
{"value": "string | number | boolean | object | null",
 "evidence": "short exact source phrase, empty when value is null",
 "confidence": "low | medium"}
```

### 2.4 Qwen 返回的合法 JSON（成功时）

```json
{"value": ["S-springs", "matte beige linen cushion", "high-resilience foam", "rattan-pattern backrest"], "evidence": "features a matte beige linen cushion wrapped over high-resilience foam and reinforced with 8 S-springs", "confidence": "medium"}
```

### 2.5 Qwen 返回的非法 JSON（失败时）

```json
{
  "value": ["S-springs", "matte beige linen cushion", "high-resilience foam", "rattan-pattern backrest", "solid wood frame"],
  "evidence": "features a matte beige linen cushion wrapped over high-resilience foam and reinforced with 8 S-springs", "ventilated rattan-pattern backrest", "Solid Wood Frame: Full hardwood construction",
  "confidence": "medium"
}
```

**错误点**：`evidence` 字符串后多了 2 个裸值 `"ventilated rattan-pattern backrest"` 和 `"Solid Wood Frame: Full hardwood construction"`。这些值没有 key，不是合法 JSON 的 key-value 对。疑似 Qwen 在输出 list 类型 value 时，将部分 value 数组元素错误地 spill 到了外层 JSON 对象中。

## 3. 根因分析

### 3.1 直接原因

Qwen `qwen-plus-latest` 模型在处理 list 类型输出时，JSON 结构偶尔损坏——数组元素被错误地放置到父级 JSON 对象中。

### 3.2 为什么容错逻辑没生效

调用链上有两层 JSON 解析：

```
上层: QwenAPIClient.generate() → json.loads(content)  ← 💥 在这里抛异常
下层: AttributeExtractionLLMClient._parse_json()       ← regex 容错，但永远不会被调用
```

`QwenAPIClient.generate()` 中 `json_mode=True` 导致 `json.loads()` 先执行并抛异常，异常向上传播经过 `DirectLLMService` 降级失败后，`AttributeExtractionLLMClient._call_client()` 只收到空 `{}`。

下层 `_parse_json()` 的 regex 容错能力被上层 `json.loads()` 短路了。

### 3.3 为什么 result_format='message' 不能保证 JSON

Qwen API 的 `result_format='message'` 表示返回 chat message 格式，不强制 JSON 结构。这与 OpenAI 的 `response_format: {type: "json_object"}` 不同。即使 prompt 强调 "Return ONLY valid JSON"，模型仍有概率输出非法 JSON。

## 4. 修复方向

### 方向 A：QwenAPIClient 加容错（上游）

```python
if json_mode:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                raise ValueError(f"无效JSON响应: {e}")
        else:
            raise ValueError(f"无效JSON响应: {e}")
    return {"content": parsed, "usage": usage}
```

### 方向 B：AttributeExtractionLLMClient 不用 json_mode（下游）

```python
# json_mode=False，用自己的 _parse_json() 做容错解析
response = llm.generate(LLMRequest(..., json_mode=False, ...))
raw = response.content
return self._parse_json(str(raw or ""))
```

改动一行，影响面仅限属性提取。

## 5. 建议

方向 B 立即修复当前问题（一行改动、零风险）。方向 A 作为根本性修复，让所有 `json_mode=True` 调用方受益。
