# ADR-2026-06-26: V2 Path-Level Review Persistence

**日期**: 2026-06-26
**状态**: Accepted

## Context

`EPIC-AMZ-LISTING-REQUIREMENT-PAYLOAD-V2` 模块设计 §12 Open Question 1 提出：V2 path-level review decisions 应该复用现有 `amz_listing_pending_review` JSONB 列，还是新建 V2 专用表以支持 queryability？

### 现状：V1 review 数据模型

`amz_listing_pending_review` 表是 SKU 级别（`UNIQUE (category, sku)`，一行 = 一个 SKU）：

```sql
id, category, sku, parent_sku,
plan_snapshot JSONB,
pending_items JSONB,       -- 待 review item 列表
review_decisions JSONB,    -- 决策列表
review_status VARCHAR(16)  -- SKU 级别状态
```

V1 review key 是顶层 `attribute`（如 `bullet_point`），pending_item 结构：

```json
{"attribute": "bullet_point", "value": "...", "evidence": "...",
 "score": 65, "route": "human", "confidence": "low", "shape": "list_value"}
```

### V2 review 需求差异

- review key 是 `path_key`（如 `frame.color`、`seat.material_type`），粒度从顶层 → 子路径
- 需要 stable path_key replay（override 不重跑 LLM）
- S11 feedback learning 需要"按 path 查历史决策"（哪些 path 经常被 Amazon 拒、AI approved vs human approved 准确率）

### 约束

- Epic §11 Rollback/Safety: "No existing production tables are dropped. New persistence, if needed, must be additive."
- Epic §4.2.1: "Review decisions and overrides must target the stable path key and must be reapplied without rerunning LLM extraction."
- Epic §6 已规划 `review_adapter_v2.py` 负责适配 V1 review workflow

## Decision

新建 V2 path-level review 表 `amz_listing_pending_review_v2`，**一行 = 一个 path-level review item**。V1 `amz_listing_pending_review` 表保持不变，cutover 后通过 `@retire` 标记退役。

### 表结构

```sql
CREATE TABLE IF NOT EXISTS amz_listing_pending_review_v2 (
    id BIGSERIAL PRIMARY KEY,
    category VARCHAR(64) NOT NULL,
    sku VARCHAR(64) NOT NULL,
    parent_sku VARCHAR(64),
    path_key TEXT NOT NULL,
    path_key_version VARCHAR(32) NOT NULL,
    attribute VARCHAR(128) NOT NULL,
    display_label TEXT,
    value JSONB,
    evidence TEXT,
    confidence_label VARCHAR(16),
    confidence_score INT,
    route VARCHAR(32) NOT NULL,
    review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    reviewer VARCHAR(64),
    verdict JSONB,
    plan_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    UNIQUE (category, sku, path_key, path_key_version)
);

CREATE INDEX idx_amz_listing_pending_review_v2_path
    ON amz_listing_pending_review_v2(path_key, review_status);
CREATE INDEX idx_amz_listing_pending_review_v2_status
    ON amz_listing_pending_review_v2(review_status, category, created_at);
CREATE INDEX idx_amz_listing_pending_review_v2_sku
    ON amz_listing_pending_review_v2(sku);
```

### 设计要点

1. **粒度**：一行 = 一个 path-level review item（不是 SKU 级别）
2. **唯一性**：`UNIQUE (category, sku, path_key, path_key_version)` 保证 stable path_key replay 的幂等性
3. **plan_snapshot 冗余存储**：每个 path item 都带完整 PayloadBuildPlan 快照。理由：plan_snapshot 是不可变快照，写入一次后不变；冗余存储避免 V2 表与 V1 表的隐式外键耦合；V1 表 cutover 后可直接 `@retire`，不影响 V2
4. **索引**：
   - `(path_key, review_status)` 支持 S11 feedback learning 的按 path 聚合查询
   - `(review_status, category, created_at)` 支持 pending 列表查询
   - `(sku)` 支持 SKU 维度查询
5. **V1/V2 隔离**：V2 表独立于 V1 表，shadow 阶段两者并存，cutover 后 V1 表 `@retire`

## Alternatives Considered

| 方案 | 优点 | 缺点 | 为何未选 |
|------|------|------|----------|
| A: 复用 V1 JSONB 列（pending_items 加 path_key 字段） | 不新增表/migration；ReviewManager persist/review/submit 流程可复用 | JSONB 扫描性能差，数据量增长后瓶颈；path_key 唯一性靠应用层保证，并发下易出 bug；V1/V2 数据混在同一 JSONB，靠 path_key_version 字段区分，易混 | S11 feedback learning 需按 path 聚合查询，JSONB 无法用索引加速；届时要么全表扫，要么 ETL 物化到另一张表（绕回方案 B） |
| B: 新建 V2 path-level 表 | path-level 索引查询；DB UNIQUE 约束保证 resume replay；V1/V2 物理隔离，cutover 清晰 | 新增表 + migration + `review_adapter_v2.py` 适配（Epic §6 已规划，预期内） | **选中** — 一次到位，避免 S11 落地时二次重构 |

## Consequences

**正面**:
- S11 feedback learning 可直接 `GROUP BY path_key` 聚合历史决策，无需 ETL
- stable path_key replay 有 DB UNIQUE 约束保障，并发安全
- V1/V2 物理隔离，cutover 时 V1 表直接 `@retire`，不污染历史数据
- plan_snapshot 冗余存储，V2 表查询无需 JOIN V1 表

**中性**:
- 短期 V1/V2 表并存，需通过 `review_adapter_v2.py` 适配（Epic §6 已规划）
- plan_snapshot 在 V2 表每行冗余一份（写入一次后不变，存储成本可接受：一个 SKU 几十 KB × N 个 path item）

**负面**:
- 多一张表，短期维护成本略高
- V1 表的 `pending_items`/`review_decisions` JSONB 列在 V2 阶段不再写入，但需保留至 cutover 完成并完成 `@retire` 流程

## Implementation Notes

- migration 文件：`migrations/amz_listing_pending_review_v2.sql`（S7 启动时创建）
- repository：`src/repositories/amazon_listing_pending_review_v2_repository.py`（S7 启动时创建）
- adapter：`src/services/review_adapter_v2.py`（S7 启动时创建，负责 V2 表 CRUD + V1 review workflow 适配）
- V1 表 `amz_listing_pending_review` 不动，cutover 后登记退役计划到 `TODO.md` 并加 `@retire` 标记

## References

- Epic: `docs/epics/listing-requirement-payload-engine-v2.md`
- 父 ADR: `docs/decisions/ADR-2026-06-26-listing-requirement-payload-engine-v2.md`
- 模块设计: `docs/module-design/listing-requirement-payload-engine-v2.md` §12
- V1 表 migration: `migrations/amz_listing_pending_review.sql`
- Phase 1 acceptance 实证: `docs/test-reports/2026-06-26-chair-phase1-acceptance.md`
