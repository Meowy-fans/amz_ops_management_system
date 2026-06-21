# ADR-2026-06-15: 采用 Schema 白名单驱动 + LLM 受限提取的属性解析流水线

**日期**: 2026-06-15
**状态**: Accepted

## Context

API-native 多类目发品已上线，但 2026-06-15 HOME_MIRROR 验收暴露了属性构建的
结构性缺陷：

- `AmazonListingPayloadBuilder.build_plan()` 对所有品类先写死一组基础属性，再靠
  各品类 YAML `remove_attributes` 反向删除。未枚举删除项的品类（HOME_MIRROR）
  会向 Amazon 提交不适用属性（5 个 WARNING，code 90000900）。
- `AmazonSchemaService.get_required_properties()` 只读 schema 顶层 `required`，
  无法识别嵌套对象 / `allOf` / 条件必填，导致 `AmazonListingAttributeCoverageGate`
  漏掉 10 个深层必填属性（ERROR，code 90220）。
- 文档约定的 LLM 提取层从未接入：`AttributeResolver._path_value()` 只支持
  `content/product/offer/variation` 根，`llm.*` 路径恒为空。资料缺失只能靠
  YAML `default` 兜底，无法从商品文案里恢复"其实写了但没结构化"的属性。

约束：必须支持多类目且不能为每个品类堆 Python 硬编码；LLM 可用于补全但存在
幻觉风险，敏感字段（品牌、identifier、合规声明、材质真实性）不能由 LLM 编造；
Amazon `VALIDATION_PREVIEW` 是唯一权威校验源。

## Decision

我们将以 Amazon Product Type Definitions schema 作为"属性清单的唯一来源"，
构建五层 schema 白名单驱动的属性解析流水线：

1. **Schema 白名单**：只生成 schema `properties` 中存在的属性，渲染末尾丢弃
   非 schema key；取消逐品类 `remove_attributes` 黑名单。
2. **必填集合 = 静态深挖 + preview 学习**：`AmazonSchemaService` 递归解析顶层 +
   嵌套 + `allOf`/条件 `required`；`ValidationFeedbackStore` 将 Amazon
   `MISSING_REQUIRED_ATTRIBUTE` 反馈合并进"学习必填集"，供 Coverage Gate 本地拦截。
3. **证据驱动取值优先级**：供应商事实 → 确定性派生 → LLM 受限提取 → 有证据默认值
   → 人工复核/阻断，命中即停。
4. **LLM 只提取不发明**：evidence 引用原文、enum 锁定、敏感字段黑名单、置信度
   上限 `medium`、输出二次校验；required 属性由 LLM 填充时走复核/警示而非静默 LIVE。
5. **Renderer 按 schema shape 渲染**：单值 / 列表 / measure+unit / 嵌套对象。

## Alternatives Considered

| 方案 | 优点 | 缺点 | 为何未选 |
|------|------|------|----------|
| A. 继续给每个品类补 `remove_attributes` 黑名单 + 手填必填 | 改动小、见效快 | 每个新品类都要人工枚举、易漏、不可扩展 | 与"多类目不硬编码"目标冲突，正是当前问题根源 |
| B. 让 LLM 直接生成完整 Amazon attributes JSON | 覆盖率高、开发省事 | 幻觉风险高，敏感/合规字段不可控 | 违反低编造风险底线 |
| C. 仅静态深挖必填，不接 preview 反馈 | 实现简单 | 条件必填仍可能漏，schema required ≠ 发品真相 | 无法自愈，HOME_MIRROR 类问题会复发 |
| D（选中）. Schema 白名单 + 证据驱动 + LLM 受限提取 + preview 学习 | 可扩展、低编造、可自愈 | renderer/extractor 工作量较大 | 同时满足扩展性、可行性、低编造三目标 |

## Consequences

**正面**:
- 新品类接入从"改 Python"变为"改配置 + strict dry-run 收 preview 反馈"。
- 不适用属性问题被白名单从根上消除，无需逐品类维护黑名单。
- 深层/条件必填本地可拦，且通过 preview 反馈持续自愈。
- LLM 提升覆盖率的同时，幻觉被 enum 锁定、证据要求和置信度天花板关进闸门。

**中性**:
- 基础属性也走 resolver/renderer，调用链变长；通过测试与 strict dry-run 回归保证等价。
- 需要新增 `ValidationFeedbackStore` 持久化与 schema shape 推断逻辑。

**负面**:
- `AttributePayloadRenderer` 与 `LLMAttributeExtractor` 改造成本较高。
- schema 白名单可能误删少量"非 schema 但 Amazon 接受"的属性，需结合 preview
  WARNING 反馈对账后再收紧。

## References

- Epic: `docs/epics/schema-driven-attribute-resolution.md`
- 模块设计: `docs/module-design/api-attribute-resolution.md`
- 前序 Epic: `docs/epics/api-native-listing-quality-pipeline.md`
- 前序任务: TASK-137 `docs/test-reports/2026-06-15-required-attribute-coverage-gate.md`
- 相关 ADR: `docs/decisions/ADR-2026-06-15-cabinet-48in-live-policy.md`
