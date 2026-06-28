# ADR-2026-06-27: Listing Rule Authoring V2 设计冻结

**日期**: 2026-06-27
**状态**: Accepted

## Context

CHAIR 等 dry-run 类目在 V2 引擎下 coverage 长期为 0，根因是 YAML 规则缺少嵌套
`children`、叶子 `path_key` 来源链，以及 product-type 级 `dimension_strategy`。
Quick validation 实验证明：补齐规则后无需改引擎主路径即可通过 Amazon
`VALIDATION_PREVIEW`。

同时存在三类缺口：

1. **Schema 静态树 ≠ Amazon 运行时必填**（如 `frame.material`、`seat.depth` 在
   analyze 树中可能缺失，preview 才暴露）
2. **`AttributeRuleLoader` 浅合并**：迁移/补丁必须写完整 attribute 块
3. **三层审核边界**：规则缺口（Layer 1）、属性值缺口（Layer 2）、Amazon 反馈学习
   （Layer 3）需分离 CLI 与持久化

## Decision

我们将采用 **Schema 驱动骨架 + 分层补全管道** 作为 Listing Rule Authoring V2
的权威方案：

1. **S1 骨架生成**复用 `RequirementTreeBuilderV2`，禁止再 fork 第三套树遍历器。
   结构父节点仅含 `children`；叶子含 placeholder `sources`。
2. **S2 字段映射**从 `_candidate_attributes_from_draft` 与 Giga 样本做 bootstrap +
   启发式字段名匹配；LLM 仅提议字段名，不写入属性值或 safe default。
3. **S3 跨类目复用**仅在 schema 子树同构（相同 path_key + shape 签名）时复制
   source 链，并标注 `inherited_from`。
4. **S4 反馈适配**读取 `amz_listing_learned_required_paths_v2`，将 90220 学到的
   Amazon 属性名映射为 YAML path_key 并补规则条目。
5. **运行时兜底**：`OptionalRuleChildrenEnricherV2` 在 compose 后并入 YAML 已定义、
   但 RequirementTree 未覆盖的可选子节点（过渡方案，S4 成熟后可收缩）。
6. **YAML 为规则真源**；`amz_listing_pending_rule_review`（S5）仅作 Layer 1 审计日志。
7. **根配置契约**：每类目 YAML 必须显式声明 `dimension_strategy`（若 schema 支持）
   与 `coverage_ignore_required`（仅 ADR 批准的 preview-only 属性）。

## Alternatives Considered

| 方案 | 优点 | 缺点 | 为何未选 |
|------|------|------|----------|
| 继续手工补 YAML | 零开发成本 | 不可扩展、易浅合并回归 | 无法支撑多类目 |
| 引擎硬编码 CHAIR 特例 | 见效快 | 破坏 V2 通用性、难维护 | 与 schema-driven 原则冲突 |
| 完全依赖 LLM 生成规则 | 覆盖快 | 合规风险、难回归 | 不允许 LLM 写 default 值 |
| Fork 独立树遍历器 | 实现自由 | 与 RequirementTree 漂移 | S1 已证明可复用 Builder |

## Consequences

**正面**:

- dry-run 类目可通过规则迭代达到 `validation_preview_passed`，引擎保持稳定
- S2–S4 管道可重复用于 TABLE、BED_FRAME 等
- 三层审核边界清晰，利于 S5/S14 切流

**中性**:

- `OptionalRuleChildrenEnricherV2` 与 S4 存在功能重叠，需后续收敛
- 跨类目复用必须验证 schema 同构，不能盲拷 SOFA `seat` 到 CHAIR

**负面**:

- 浅合并要求迁移写全块，人工编辑成本高
- learned path 使用 Amazon 下划线命名，需映射层维护
- 生产镜像需同步 YAML + 新服务代码才能生效

## References

- Epic: `docs/epics/listing-rule-authoring-v2.md`
- Phase 4 extension: `docs/decisions/ADR-2026-06-28-category-rule-lifecycle-scope.md`
- Dev plan: `docs/plans/category-rule-lifecycle-dev-plan.md`
- 模块设计: `docs/module-design/rule-skeleton-generator-v2.md`
- Quick validation: `docs/test-reports/2026-06-27-chair-quick-validation.md`
- 前置 ADR: `docs/decisions/ADR-2026-06-26-listing-requirement-payload-engine-v2.md`
