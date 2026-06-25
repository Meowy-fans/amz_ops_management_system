# E2E 验收总结（2026-06-22）

## 一、做了什么

对 **API-Native 发品全链路** 做了端到端验收，以 CHAIR 品类为主战场。

### 1.1 从 0 到 1：打通完整链路

```
起点: Giga 收藏品 (409 SKUs, 135 待发品)
  → auto-discover-category (22 个未映射品类 → 手动映射 9 个)
  → AttributeRuleGenerator (为 8 个新品类生成 YAML 规则)
  → 3 轮架构迭代:
      第 1 轮: universal preset（解决 Step2/3 双路径冲突）
      第 2 轮: safe default 白名单（解决 default: null 阻断）
      第 3 轮: 自动 LLM source + 白名单机制（让任意 required 属性有提取机会）
  → 发品到 Amazon LIVE

终点: 1 个 CHAIR SKU 成功到达 Amazon PUT 端点 ✅
```

### 1.2 SOFA 品类全量发品

- 单发 4 个 + 变体家族 2 个（2 父品 + 13 子体）= 19 个 SKU 提交成功
- 修复了 `variation_theme_strategy.yaml` 缺失 SOFA 配置的问题
- 1 个 SKU 获得 ASIN（B0H685TQGZ），可在 Amazon 验收

---

## 二、核心架构问题及解决

| # | 问题 | 状态 |
|---|------|------|
| 1 | Step2(PayloadBuilder) 和 Step3(Resolver) 双路径对同一属性给出矛盾结论 → CoverageGate 阻断 | ✅ 已修复 — universal preset + PayloadBuilder 迁移 |
| 2 | `_DEFAULT_SOURCE_CANDIDATES` 只覆盖 23 个属性，其余 required 全部 `default: null` | ✅ 已修复 — 自动 llm source + safe default 白名单 |
| 3 | 自动生成 YAML 的 `default: null` 被 CoverageGate 阻断 | ✅ 已修复 — `UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE` gate |
| 4 | Qwen LLM list 类型 JSON 间歇性损坏（~33% 失败率） | ✅ 已修复 — `json_mode=False` + 下游容错 |
| 5 | `required + llm → needs_manual_review` 阻断所有 LLM 提取值 | 🔴 待修复 |
| 6 | `item_depth_width_height` 等维度属性 Resolver 与 PayloadBuilder 冲突 | 🔴 待修复 |
| 7 | 3 个属性（frame/seat/max_weight）shape 与 Amazon Schema 不匹配 | 🔴 待修复 |

---

## 三、当前状态

```
CHAIR 品类 18 个 SKU:
  └── 1 个到达 Amazon → INVALID（3 个 payload 格式问题）
  └── 其余 17 个被 CoverageGate 阻断（needs_manual_review 问题）

SOFA 品类 19 个 SKU:
  └── 全部提交成功 ✅

其他 7 个品类:
  └── 到达 Amazon 但 INVALID（品类特定属性缺失，需逐品类配置）

未映射品类:
  └── 31 SKUs（11 个类别无法 auto-discover）
```

---

## 四、待解决问题（6 项）

| # | 问题 | 优先级 |
|---|------|--------|
| 1 | `needs_manual_review` 有 safe_default 时应不阻断 | 高 |
| 2 | `is_fragile`/`item_shape` 需永久加入 safe_default | 高 |
| 3 | 维度属性需从生成器永久排除 | 中 |
| 4 | 新品类需自动检测 `dimension_strategy` | 中 |
| 5 | `frame`/`seat`/`max_weight_recommendation` YAML shape 修正 | 中 |
| 6 | Qwen JSON 上游容错 | 低（已有临时修复） |

---

## 五、关键文档

- `docs/proposals/e2e-issues-summary.md` — E2E 发现的问题清单
- `docs/proposals/step3-unified-attribute-pipeline.md` — Step3 统一管线方案
- `docs/proposals/attribute-rule-generator-fix.md` — Generator 补齐方案
- `docs/proposals/generator-universal-llm-fallback.md` — LLM fallback 方案
- `docs/proposals/llm-json-parse-failure-diagnosis.md` — Qwen JSON 诊断
- `docs/proposals/e2e-acceptance-findings-and-fixes.md` — E2E 发现与修复详情
