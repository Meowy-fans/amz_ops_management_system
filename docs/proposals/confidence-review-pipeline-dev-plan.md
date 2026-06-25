# 开发方案：Evidence-Grounded 分级审核闭环（Confidence Review Pipeline）

- **状态**：`Implemented (dev, not deployed)`
- **日期**：2026-06-25
- **合并来源**：`confidence-based-review-pipeline.md`（评分路由）+ `human-in-the-loop-review-design.md`（闭环骨架）
- **目标**：解决 `required + llm → needs_manual_review, blocking=True` 一律阻断的问题，让“可信值自动通过、可疑值经审核后继续发品”，并形成可持久化、可恢复的业务闭环。

---

## 0. 为什么要合并两份提案

- `human-in-the-loop-review-design.md` 给出了**闭环骨架**：`pending_reviews / review_decisions / attribute_overrides / review_status` + resume CLI。
- `confidence-based-review-pipeline.md` 给出了**路由依据**：evidence-grounding 客观评分。
- 二者职责互补、不冲突。本方案以 HITL 为流程主干，confidence 评分作为路由器，合并实施，避免出现两套 review 模型。

---

## 1. 根因复述（与代码对齐）

阻断由两处联动产生，二者都要改：

```277:279:src/services/attribute_resolver.py
        if result.source == "llm" and result.level == "required":
            result.state = "needs_manual_review"
            result.blocking = True
```

```166:176:src/services/amazon_listing_attribute_coverage_gate.py
    def _is_low_confidence_required(resolution):
        ...
        or resolution.get("confidence") == "low"
        or bool(resolution.get("blocking"))
```

`AttributeResolution` 已带 `evidence` 字段（来自 LLM extractor），evidence-grounding 在数据上可行：

```22:23:src/services/attribute_resolver.py
    evidence: str = ""
    confidence: str = "low"
```

---

## 2. 必须修正的 4 个硬伤（来自前次 review）

| # | 原方案问题 | 本方案修正 |
|---|-----------|-----------|
| H1 | resolver 短路：被评分人群（source=llm）的 path 恒为 null，评分表中 `path 有值(20)+path==llm(15)` 共 35 分**结构性不可达** | 评分**去掉 path 双值信号**，权重重标定到“evidence-grounding 为主”的可达区间 |
| H2 | Phase 1 无历史数据时最高仅 45 分 < 50，**0 自动通过**（冷启动死锁） | 重标定阈值：Phase 1 不依赖 history 即可自动通过；history 作为后期增量 |
| H3 | 缺持久化/恢复层，Phase 3 是空中楼阁，**不构成闭环** | 先建 `amz_listing_pending_review` 表 + ReviewManager，闭环优先 |
| H4 | 示例 frame/seat 在 S1 后已变 object→不再走 llm，作用域过期 | 重新界定作用域：仅 `source=llm & level=required` 的 needs_manual_review 属性 |

---

## 3. 评分模型（重标定后）

### 3.1 可用客观信号（对被评分人群真实可得）

| 信号 | 来源 | 权重 |
|------|------|------|
| evidence 模糊命中原始 context | `LLMAttributeExtractor._context` 重建后字符串匹配 | 45 |
| evidence 长度 ≥ 20 | 计算 | 10 |
| 值在 Amazon enum 内（仅 enum_locked 属性） | `get_cached_valid_values` | 15 |
| LLM 自评非 low | `extraction.confidence` | 10 |
| 历史审核准确率 ×20（Phase 4 接入，默认 0） | 审核记录统计 | 20 |

> Phase 1 可达上限 = 45+10+15+10 = **80**（enum 属性）/ 70（非 enum）。阈值因此可落在可达区间。

### 3.2 路由阈值（Phase 1 即生效）

```
分数      模式            说明
────────────────────────────────────────
≥ 55     auto_approved   evidence 命中且长度达标 → 直接使用
35-54    ai_agent        evidence 命中但偏弱 → AI 验证
< 35     human           evidence 缺失/未命中 → 人工
```

`evidence` 命中(45)+长度(10)=55 即可在 Phase 1 自动通过，**不依赖 history**，破解冷启动。

---

## 4. 架构与数据流

```
Resolver.resolve() → needs_manual_review 属性
  → ConfidenceScorer.score(resolution, context)        # 客观评分
     ≥55 auto_approved → review_decisions + attribute_overrides（即时，无需持久化）
     其余 → ReviewManager.persist_pending(plan)         # 落库，plan 标记 needs_review，不提交

CLI: review-pending-attributes --category CHAIR
  → ReviewManager.load_pending() → AI Agent / Human 裁决 → 写回 review_decisions

CLI: submit-reviewed-plans --category CHAIR
  → 注入 attribute_overrides → 重建 plan（Resolver 跳过有 override 的 llm 提取）
  → CoverageGate 重判（override 后 blocking=False）→ Submit
```

---

## 5. 模块与改动清单

### 5.1 新增

| 模块 | 路径 | 职责 |
|------|------|------|
| `ConfidenceScorer` | `src/services/confidence_scorer.py` | 接收 resolution + context，产出 0-100 分与路由 |
| `AttributeReviewAgent` | `src/services/attribute_review_agent.py` | AI 验证单属性，verdict=correct/incorrect/uncertain；**仅判 evidence 是否字面命中**，降低同源自欺 |
| `ReviewManager` | `src/services/review_manager.py` | pending 生命周期：persist / load / apply_decisions / mark_completed |
| `AmazonListingPendingReviewRepository` | `src/repositories/amazon_listing_pending_review_repository.py` | 持久化 CRUD（SQLAlchemy `text()`，对齐现有 repo 风格） |
| review 配置 | `config/listing_gates/review_policy.yaml` | 权重 / 阈值 / AI 开关 / bypass 白名单 |

### 5.2 改造

| 文件 | 改动 |
|------|------|
| `attribute_resolver.py` | `resolve(draft, overrides=None)`：override 命中则跳过 source 链直接采用；`_finish` 的 `source=="llm"` 分支不再硬写 `blocking=True`，改为标 `needs_manual_review` 但 blocking 交由评分/gate 决策 |
| `amazon_listing_attribute_coverage_gate.py` | `_is_low_confidence_required` 解耦：`needs_manual_review` 且已有 `review_status=completed/auto_approved` 的不再算阻断 |
| `product_listing_api_plan_builder.py` | coverage 阻断且属于 needs_manual_review 时，不直接丢弃，转交 ReviewManager 持久化为 `needs_review` |
| `operation_handlers.py` / `main.py` | 注册 `review-pending-attributes`、`submit-reviewed-plans` 两个 CLI（带 `--category`，避免 EOF 交互） |

### 5.3 持久化表（关键闭环落点）

```sql
CREATE TABLE amz_listing_pending_review (
    id              BIGSERIAL PRIMARY KEY,
    category        VARCHAR(64)  NOT NULL,
    sku             VARCHAR(64)  NOT NULL,
    parent_sku      VARCHAR(64),
    plan_snapshot   JSONB        NOT NULL,   -- 完整 plan，供 resume 重建
    pending_items   JSONB        NOT NULL,   -- [{attribute, llm_value, evidence, score, route}]
    review_decisions JSONB       NOT NULL DEFAULT '[]',
    review_status   VARCHAR(16)  NOT NULL DEFAULT 'pending', -- pending/in_progress/completed
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (category, sku)
);
```

---

## 6. 实施阶段（每阶段独立可验收）

| 阶段 | 内容 | 验收标准 |
|------|------|---------|
| **P1 评分+即时自动通过** | ConfidenceScorer + resolver/gate 解耦 + 配置 | CHAIR dry-run：evidence 命中的 required-llm 属性 `auto_approved` 入 attribute_overrides，不再 `blocked_attribute_coverage`；单测覆盖评分边界 |
| **P2 持久化+恢复 CLI** | 表 + Repository + ReviewManager + 两个 CLI | needs_review 落库；`submit-reviewed-plans` 注入 override 后 resume 提交成功；resume 不重复跑 LLM |
| **P3 AI Agent 审核** | AttributeReviewAgent + 35-54 路由 | AI verdict 写回 review_decisions；object/sensitive/空 evidence 强制转 human |
| **P4 历史准确率** | 审核结果回流统计 + history 权重接入 + bypass 白名单自动维护 | history≥min_samples 时分数提升，人工量进一步下降 |

---

## 7. 关键风险与护栏（保持 fail-closed）

1. **resume 一致性**：override 优先级最高，重建时 resolver 命中 override 即跳过 LLM，杜绝重提取漂移。
2. **object/measure 属性**：不在本 pipeline 作用域（S1 后走 missing_required），仍由 CoverageGate 硬阻断，安全默认不变。
3. **敏感属性**：`_SENSITIVE_MARKERS`（gtin/compliance/certification…）一律不进 auto_approve、不进 AI，直转 human。
4. **AI 自欺防护**：AttributeReviewAgent 只裁定“evidence 是否字面出现在原始 context”，不重新发挥。
5. **Phase 1 灰度**：`review_policy.yaml` 加 `enabled` 开关与品类白名单，先 CHAIR 验证再放量。

---

## 8. 与既有约束的对齐

- 遵循 `~/DEV_GUIDELINES.md` 七阶段与 TDD：每阶段先写单测/golden 再实现。
- 新增 service 需同时创建 `AI_SUMMARY.md`（ConfidenceScorer / ReviewManager / AttributeReviewAgent）。
- 表结构变更同步 `/data/README.md` 服务清单与 `/data/TODO.md`。
- 部署沿用固定 tag + `deploy.sh`，生产镜像不含 pytest，验收用 host 端测试 + 容器内脚本校验。
