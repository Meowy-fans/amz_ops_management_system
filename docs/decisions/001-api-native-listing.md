# ADR-001: API-Native 发品替代 Excel 模板发品

**日期**: 2026-06-13
**状态**: Accepted (retrospective — 实际决策发生于 2026-05 至 2026-06)

## Context

2025 年 11 月至 2026 年 5 月，系统使用 Excel 模板发品路径：下载 Amazon 品类模板（.xlsm），用 `ExcelGenerator` 填充数据，手动上传。该路径有以下问题：

1. Amazon 品类模板字段频繁变化，`amz_template_parser.py` 需持续适配 Valid Values
2. 模板解析依赖硬编码的品类字段映射（`amz_listing_data_mapping/` JSON），维护成本高
3. 手动上传环节无法自动化闭环
4. 变体父子关系需要手工在 Excel 中维护多行

2026 年 5 月引入了 Amazon SP-API Listings Items API，直接通过 API 创建/更新 Listing。这开启了 API-native 发品路径。

## Decision

我们将 API-native 发品（`generate-listing-api` → `AmazonListingDraft` → `AmazonListingPayloadBuilder` → `AmazonListingSubmitter`）作为**唯一新品发品入口**。

Excel 模板发品路径（`generate-listing`、`ExcelGenerator`、`amz_template_parser` 等）标记为 deprecated，保留为历史数据兼容和排障参考，不再作为运营入口。

## Alternatives Considered

| 方案 | 优点 | 缺点 | 为何未选 |
|------|------|------|----------|
| 保留双路径 | 风险低，兼容已有流程 | 维护两份代码，Excel 模板适配持续消耗时间 | 双路径并存的维护成本高于一次性迁移 |
| 直接删除 Excel 路径 | 代码最干净 | 历史数据仍需 Excel 模板解析来排障 | 风险过高，需先确认无历史依赖 |

## Consequences

**正面**:
- 发品流程全自动化，无需手动下载/上传 Excel
- 通过 `getListingsItem` 实现实时查重和提交后确认
- 属性构建可基于 Product Type Definitions schema 做合法值对齐

**负面**:
- Excel 模板/文件生成代码仍保留到 `2026-07-31` 删除窗口，用于历史排障和迁移参考
- `product_listing_service.py` 在兼容窗口内仍保留少量 legacy Excel 函数，但这些函数已带 `@retire` 标记
- `generate-listing` 仍作为 deprecated alias 注册到 API-native dry-run，兼容窗口结束后可移除

## References

- 退役计划: `docs/retirement/excel-listing-retirement-2026-06-15.md`
- Epic: `docs/epics/api-native-listing-quality-pipeline.md`
- 生产部署验收: `docs/test-reports/2026-06-15-api-native-quality-production-deploy.md`
- 相关 PR: `8ec047f`（Orders Phase A）, `6ca1e6f`（API-native hardening）
- 被本 ADR 详细阐述的决策最早出现在: `d11742e feat(amz-listing): multi-source product listing pipeline with SP-API`
