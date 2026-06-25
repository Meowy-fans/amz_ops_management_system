# 方案设计：Human-in-the-Loop 属性审核流程

- **日期**：2026-06-22
- **关联**：E2E Case 1 — `needs_manual_review` 过度阻断

---

## 1. 背景

当前 `required + llm → needs_manual_review, blocking=True` 直接将发品流程终止，没有任何机制让人类或 AI Agent 介入审核后继续。

系统设计意图是 Human-in-the-Loop：LLM 提取了 required 属性的值 → 标记为待审核 → 人类（或 AI Agent）审核确认 → 继续发品。当前只有"标记"和"阻断"，缺少"审核"和"继续"。

## 2. 审核时具备的信息

当属性被标记为 `needs_manual_review` 时，以下信息已经可用：

```python
{
    "attribute": "frame",           # 属性名
    "llm_value": "Solid Wood",      # LLM 提取的值
    "llm_evidence": "Solid Wood Frame: Full hardwood...",  # LLM 引用的证据
    "llm_confidence": "medium",     # LLM 置信度

    # 审核者可以用来验证的原始上下文（与发送给 LLM 的 context 相同）
    "context": {
        "title": "Solid Wood Rattan Back Dining Chair...",
        "bullets": ["Solid Wood Frame: ...", ...],
        "description": "<b>Experience Lasting Comfort...</b>...",
        "product_attributes": {"Main Material": "Linen", "Seating Quantity": "Set of 2", ...},
        "raw_name": "Solid Wood Rattan-Back Dining Chair, ...",
        "raw_characteristics": ["Solid Wood Construction - Made of full solid wood...", ...]
    },

    # 属性约束
    "valid_values": [],              # enum_locked 时的合法值列表
    "enum_locked": false,            
    "safe_fallback": null            # 链中有 safe_default 时的兜底值
}
```

## 3. 目标流程

```
Resolver → needs_manual_review
  → Plan 进入"待审核"状态（不阻断，暂停）
    → 审核者介入：
        ├── [Human]  CLI 展示审核项 → 人确认/修改/跳过
        └── [AI Agent] 读取原始信息 → 逐属性验证 → 自动确认/修正/标记为人工
    → 审核结果写回 Plan
    → Plan 恢复 → CoverageGate → Submit
```

## 4. 数据模型

### 4.1 审核项（ReviewItem）

```python
@dataclass
class ReviewItem:
    attribute: str              # 属性名
    llm_value: Any              # LLM 提取的值
    llm_evidence: str           # LLM 证据原文
    llm_confidence: str         # low / medium
    context: Dict               # 提供给 LLM 的原始上下文
    valid_values: List[str]     # 合法值（如有）
    enum_locked: bool
    safe_fallback: Any          # 链中的 safe_default 值（如有）

@dataclass  
class ReviewDecision:
    action: str                 # "approved" | "overridden" | "skipped"
    approved_value: Any         # approved 时为 llm_value，overridden 时为修正值，skipped 时为 safe_fallback
    reviewer: str               # "human" | "ai_agent"
    reason: str                 # 审核理由
```

### 4.2 Plan 中的审核元数据

```python
plan["pending_reviews"] = [ReviewItem, ...]       # 待审核项
plan["review_decisions"] = [ReviewDecision, ...]   # 已完成的审核决定
plan["review_status"] = "pending" | "partial" | "completed"
```

## 5. AI Agent 审核

### 5.1 审核方式

AI Agent 收到的不是"提取属性值"的任务，而是"验证已有提取是否正确"的任务。这是一个更简单的二元判断：

```
Prompt:
  以下是 Amazon 商品属性 "{attribute}" 的 LLM 提取结果：
  - 提取值: {llm_value}
  - 引用证据: {llm_evidence}

  以下是原始商品信息：
  {context}

  请验证提取值是否与原始信息一致：
  1. 证据原文是否真实存在于原始信息中？
  2. 提取值是否与证据原文匹配？
  3. 如果不一致，正确的值应该是什么？

  返回 JSON:
  {
    "verdict": "correct" | "incorrect" | "uncertain",
    "corrected_value": ... | null,
    "reason": "..."
  }
```

AI Agent 可以访问所有 Giga 原始数据（raw_name、raw_characteristics、product_attributes 等），交叉验证 LLM 的证据和值。

### 5.2 能力边界

AI Agent 适合审核的属性类型：
- 有明确原文支撑的提取（如 `number_of_items = 2`，证据"Set of 2"可直接在 product_attributes 中找到）
- 简单事实判断（如 `is_assembly_required = True`，证据"hardware included"）

AI Agent 不适合审核的（转为人工）：
- 需要专业领域知识（如 `bike_type` → mountain/road/hybrid 的区分）
- 证据模糊、置信度 low
- 多个合法值之间选择不确定

## 6. 人类审核

### 6.1 CLI 命令

```
review-pending-attributes --category CHAIR [--auto-approve-above 0.9]
```

对每个待审核属性展示：

```
=== number_of_items ===
LLM 提取值:   2
证据:         Seating Quantity: "Set of 2"
原始数据:
  product_attributes: {"Seating Quantity": "Set of 2", ...}
  title: "Solid Wood Rattan Back Dining Chair - ..."
  characteristics:
    · Solid Wood Construction - Made of full solid wood...

操作:
  [a] 确认 (approved)    [o] 修改 (override)    [s] 跳过 (skip)
  > a
  
✅ number_of_items: confirmed → 2
```

### 6.2 批量审核模式

当多个 SKU 有相同的属性需要审核时，可以批量确认：

```
=== frame (5 SKUs need review) ===
  meow2511081Gqqd: Solid Wood     ← evidence: "Solid Wood Frame: Full hardwood..."
  meow251108fKlrr: walnut bentwood ← evidence: "Walnut Bentwood Back & Metal Legs"
  meow251108ZNCVC: iron tube       ← evidence: "with iron tube wood color legs"
  ...

  [a] 全部确认    [o] 逐个修改    [s] 全部跳过
```

## 7. 与发品流程的集成

### 7.1 Pipeline 中的位置

```
ProductListingAPIPlanBuilder.build_for_category()
  → 构建 Plans
  → 对每个 Plan:
      if plan 有 pending_reviews:
        → plan 标记为 "needs_review"，不提交
      else:
        → 正常提交

CLI: review-pending-attributes
  → 加载 pending plans
  → 人类/AI Agent 审核
  → 写回 review_decisions
  → 标记 review_status = "completed"

CLI: submit-reviewed-plans
  → 加载 review_completed plans  
  → 将 review_decisions 中的值注入 attribute_overrides
  → CoverageGate (使用已审核值重判)
  → Submit
```

### 7.2 属性覆盖机制

审核后的值通过 `attribute_overrides` 传入 Resolver，跳过 LLM 提取：

```python
plan["attribute_overrides"] = {
    "frame": {"value": "Solid Wood", "source": "human_review"},
    "number_of_items": {"value": 2, "source": "ai_agent_review"},
}
```

Resolver 发现 `attribute_overrides` 中有值时，直接使用，不走 source 链。

## 8. 审核模式配置

```yaml
# config/listing_gates/review_policy.yaml
review_policy:
  default_mode: human        # human | ai_agent | bypass
  
  # AI Agent 可自动审核的条件
  ai_agent_rules:
    - confidence_min: medium      # LLM confidence >= medium
    - evidence_length_min: 10     # 证据至少 10 个字符
    - exclude_attributes: []      # 永远不自动审核的属性
    - verdict_threshold: 0.9      # AI Agent 确信度阈值
    - fallback_to_human: true     # AI 不确定时转人工
  
  # 不需要审核的情况
  bypass_when:
    - has_safe_default: false     # 有 safe_default 时可以跳过审核
    - attributes: []              # 特定属性永远不审核
```

## 9. 总结

| 角色 | 触发方式 | 能力 | 限制 |
|------|---------|------|------|
| Human | CLI 交互 | 全部属性 | 需要人工时间 |
| AI Agent | 自动/CLI 触发 | 事实核对（evidence vs source） | 不确定时转人工 |
| Bypass | has_safe_default | 有兜底 → 自动通过 | 需要预设白名单 |

三种模式互补，不互相替代。`review_policy.yaml` 控制策略。
