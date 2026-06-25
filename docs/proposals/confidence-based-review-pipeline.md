# 方案提案：基于客观置信度的分级审核管道

- **状态**：`Review`
- **日期**：2026-06-22
- **关联**：E2E Case 1 — `needs_manual_review` 审核机制

---

## 1. 需求说明

本方案引入**统一的客观置信度评分**作为审核路由的唯一依据。以下旧置信度来源全部退役：

| 退役项 | 当前位置 | 退役原因 |
|--------|---------|---------|
| LLM 自评 confidence（low/medium） | `_cap_confidence()` → `_finish()` | 模型自我评估不可靠，幻觉也可能是 medium |
| path source 硬编码 `confidence: high` | `_read_source()` line 132 | 不验证 Giga 数据质量，有值就 high |
| default source YAML 配置 confidence | YAML 文件中人工填写 | 人可能未审核就填了 medium |
| `_finish()` 中的 `confidence == "low"` 阻断规则 | `_finish()` line 267-269 | 被客观评分替代 |

退役后：
- `_finish()` 不再根据 source 类型和旧 confidence 做 blocking 判定
- `AttributeResolution.confidence` 字段保留但不再作为阻断依据
- 审核路由唯一依据：`ConfidenceScorer.score()` 产出的 0-100 客观分

---

## 2. 背景

### 2.1 问题

当前 `required + llm source → needs_manual_review, blocking=True` 将所有 LLM 提取的 required 属性值一律阻断，发品流程到此终止。没有任何审核、确认、继续的机制。

审核工作量过大：一个 CHAIR SKU 有 6-8 个 `needs_manual_review` 属性，18 个 SKU = 100+ 个属性全部需要人审。

### 1.2 目标

- 可信的值自动通过，减少人工审核量
- 可疑的值经 AI Agent 或人类审核后，流程可以继续
- 审核决策有据可查（evidence grounding）

---

## 3. 核心设计：客观置信度评分

### 3.1 设计原则

所有旧置信度来源已退役（见第 1 节）。新方案只使用从 Resolver 执行过程中可获取的客观信号，不依赖 LLM 自评、不依赖 YAML 硬编码。

### 2.2 客观信号

每个属性提取完成后，系统已有以下事实，不需要再调 LLM：

| 信号 | 来源 | 确定性 |
|------|------|--------|
| evidence 是否在原始 context 中存在 | 字符串精确/模糊匹配 | 100% 客观 |
| evidence 长度 | 计算 | 100% 客观 |
| path source 是否也拿到了值 | Resolver 执行记录 | 100% 客观 |
| path 值与 LLM 值是否一致 | 对比 | 100% 客观 |
| 值是否在 Amazon enum 中 | Schema validValues | 100% 客观 |
| 该属性历史审核准确率 | 审核记录统计 | 数据驱动 |

### 2.3 评分表

```
信号                              权重    计分规则
─────────────────────────────────────────────────────────
evidence 在 context 中存在          30     模糊匹配命中=30, 未命中=0
evidence 长度 ≥ 20 字符             10     是=10, 否=0
path 也拿到了值                     20     非 null=20, null=0
path 值 == LLM 值                  15     一致=15, 不一致=-15, path null=0
值在 Amazon enum 中                  5     在=5, 不在=0
历史准确率 × 20                     20     如 90% → 18 分，无历史=0
─────────────────────────────────────────────────────────
满分                               100
```

### 2.4 路由阈值

```
分数      审核模式              含义
──────────────────────────────────────────
≥ 50     自动通过               evidence grounded，直接使用 LLM 值
30 - 49  AI Agent 审核         有部分信号，AI 辅助确认
< 30     Human 审核            信号太弱，需要人来判断
```

LLM 自评 `confidence: low` → 额外降一级（≥ 50 的降到 AI Agent，30-49 的降到 Human）。

### 2.5 示例

**number_of_items = 2, evidence = "Seating Quantity: Set of 2"**

```
evidence 在 context 中?  product_attributes["Seating Quantity"] = "Set of 2" → 30
evidence 长度 ≥ 20?      26 chars → 10
path 有值?               null → 0
path == LLM?             N/A → 0
在 enum 中?              无 → 0
历史准确率?              100% (10/10) → 20
──────────────────────────────────
总分: 60 → 自动通过 ✅
```

**frame = "rubberwood", evidence = "Sturdy rubberwood frame..."**

```
evidence 在 context 中?  全文搜索 "rubberwood" → 0
evidence 长度 ≥ 20?      是 → 10
path 有值?               null → 0
path == LLM?             N/A → 0
在 enum 中?              无 → 0
历史准确率?              无 → 0
──────────────────────────────────
总分: 10 → Human 审核 🔴
```

---

## 4. 审核模式

### 3.1 AI Agent 审核

**输入**：与 LLM 提取时完全相同的 context + LLM 提取结果

**任务**：验证，不是重新提取。Prompt 设计：

```
以下是 LLM 对商品属性 "{attribute}" 的提取结果：
- 提取值: {llm_value}
- 引用证据: {llm_evidence}

以下是商品的原始信息：
{context}

请验证提取值是否与原始信息一致：
1. 证据原文是否真实出现在原始信息中？
2. 提取值是否与证据原文匹配？
3. 如果不一致，正确的值是什么？

返回 JSON:
{"verdict": "correct" | "incorrect" | "uncertain",
 "corrected_value": ... | null,
 "reason": "..."}
```

**输出**：三种 verdict：

| verdict | 含义 | 后续动作 |
|---------|------|---------|
| `correct` | LLM 值正确 | attribute_overrides 用 LLM 值，继续发品 |
| `incorrect` | LLM 值错误 | attribute_overrides 用 corrected_value，继续发品 |
| `uncertain` | AI 不确定 | 转 Human 审核 |

**限制**：以下情况不路由到 AI Agent，直接转 Human：
- shape 为 object/nested_object（结构复杂）
- 属性名命中 `_SENSITIVE_MARKERS`（compliance/certification 等高风险）
- evidence 为空（无信息可验证）

### 3.2 Human 审核

CLI 命令：`review-pending-attributes --category CHAIR`

对每个待审核属性展示 LLM 提取结果、证据、原始上下文、置信度分数：

```
=== frame (score: 10/100) ===
LLM 提取值:   rubberwood
证据:         "Sturdy rubberwood frame..." ⚠️ 在原文中找不到
原始信息:
  title: "Solid Wood Rattan Back Dining Chair..."
  characteristics:
    · "Solid Wood Construction - Made of full solid wood..."  ← "solid wood" NOT "rubberwood"
  product_attributes: {"Main Material": "Linen", ...}

操作: [a] 确认 LLM 值  [o] 输入修正值  [s] 使用 safe_default
>
```

批量模式（多个 SKU 同属性）：

```
=== frame (5 SKUs need review) ===
  meow2511081Gqqd: Solid Wood     ← evidence found ✅
  meow251108fKlrr: walnut bentwood ← evidence found ✅
  meow251108QOPQp: rubberwood      ← evidence NOT found ⚠️
  ...

  [a] 确认全部  [o] 逐个处理  [s] 全部跳过
```

---

## 5. Pipeline 集成

### 4.1 数据模型

```python
@dataclass
class ReviewDecision:
    attribute: str
    verdict: str              # "auto_approved" | "ai_correct" | "ai_incorrect" | "human_approved" | "human_overridden" | "skipped"
    approved_value: Any
    reviewer: str             # "confidence_score" | "ai_agent" | "human"
    original_llm_value: Any
    confidence_score: int
    reason: str

# Plan 中新增字段
plan["pending_reviews"] = [ReviewItem, ...]
plan["review_decisions"] = [ReviewDecision, ...]
plan["review_status"] = "pending" | "in_progress" | "completed"
plan["attribute_overrides"] = {attr: {"value": ..., "source": "review"}}
```

### 4.2 流程

```
Resolver.resolve()
  → needs_manual_review 属性
    → ConfidenceScorer.score() → 计算客观置信度
      → score ≥ 50: auto_approved → 写入 review_decisions → attribute_overrides
      → score 30-49: 路由到 AI Agent
        → AI 审核 → correct/incorrect/uncertain
      → score < 30: 路由到 Human

Plan 有 pending_reviews 且非全部 auto_approved:
  → Plan 标记 review_status = "pending"
  → 不提交，等待审核

审核完成:
  → review_status = "completed"
  → attribute_overrides 注入已审核值
  
Resume Pipeline:
  → Resolver 检查 attribute_overrides → 有则跳过 LLM 提取
  → CoverageGate 重判（审核后 blocking=False）
  → Submit
```

### 4.3 新增模块

| 模块 | 职责 |
|------|------|
| `ConfidenceScorer` | 接收 Resolution + Draft context，计算 0-100 客观置信度分数 |
| `AttributeReviewAgent` | AI Agent 审核单个属性，返回 verdict |
| `ReviewManager` | 管理 Plan 的 review 生命周期（pending → in_progress → completed）|

---

## 6. 配置

```yaml
# config/listing_gates/review_policy.yaml
review_policy:
  confidence_scoring:
    weights:
      evidence_found: 30
      evidence_length: 10
      path_has_value: 20
      path_matches_llm: 15
      enum_match: 5
      historical_accuracy: 20
    evidence_match_mode: fuzzy      # exact | fuzzy (模糊匹配)
    historical_min_samples: 5       # 至少 N 次历史记录才启用历史准确率

  routing:
    auto_approve_threshold: 50      # ≥ 此分数自动通过
    ai_agent_threshold: 30          # ≥ 此分数走 AI Agent，< 此分数走 Human
    llm_low_confidence_penalty: true # LLM 自评 low 时降一级

  ai_agent:
    enabled: true
    exclude_shapes: [object, nested_object]
    exclude_markers: [compliance, certification, regulation, gtin, identifier, hazmat]
    
  bypass_attributes:               # 已验证可靠，跳过所有审核
    - number_of_items
```

---

## 7. 效果预估

以 CHAIR SKU `meow2511081Gqqd` 的 6 个 `needs_manual_review` 属性为例：

| 属性 | LLM 值 | evidence 在原文? | 预估分数 | 路由 |
|------|--------|-----------------|---------|------|
| number_of_items | 2 | ✅ | 60 | 自动通过 |
| frame | Solid Wood | ✅ | 57 | 自动通过 |
| max_weight | 300 | ✅ | 50 | 自动通过 |
| is_assembly_required | True | ✅ | 50 | 自动通过 |
| seat | foam-filled... | ✅ | 47 | AI Agent |
| included_components | [5 items] | ⚠️ 部分 | 40 | AI Agent |

**人工审核量：6 → 0**（4 个自动通过 + 2 个 AI Agent 处理）。

---

## 8. 实施阶段

| 阶段 | 内容 | 依赖 |
|------|------|------|
| Phase 1 | `ConfidenceScorer` + evidence grounding + 评分路由 | 无 |
| Phase 2 | `AttributeReviewAgent` + AI Agent 审核 | Phase 1 |
| Phase 3 | `ReviewManager` + Plan 暂停/恢复 + CLI 人审 | Phase 2 |
| Phase 4 | 历史准确率统计 + bypass 白名单自动更新 | Phase 3 |
