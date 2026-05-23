# Amazon Listing Issue Monitoring

## 目标

运营场景需要及时发现并处理 Seller Central 中的 listing issue、search suppression 和质量警告。本模块通过官方 SP-API 定时同步问题，入库后启动修复流程。

## 数据来源

1. `getListingsItem` with `includedData=summaries,issues,productTypes`
   - 按本地 `amz_all_listing_report` 中的 SKU 查询。
   - 获取 issue code、severity、message、attributeNames、categories、enforcements。
2. Reports API `GET_MERCHANTS_LISTINGS_FYP_REPORT`
   - 批量获取 Search Suppressed listing。
   - 获取 SKU、ASIN、Reason、Issue Description。

## 数据表

- `amazon_listing_issue_scan_runs`: 每轮扫描记录。
- `amazon_listing_issues`: 当前和历史 issue，按 `sku + marketplace_id + issue_key` 幂等 upsert。
- `amazon_listing_issue_actions`: 修复计划和执行记录。

## 修复策略

默认行为是 dry-run，只生成修复动作，不提交 Amazon 写操作。

当前策略：

- `MISSING_ATTRIBUTE` + `recommended_uses_for_product`
  - 若本地已缓存该 product type schema 且确认属性存在，生成 `patchListingsItem` payload。
  - dry-run 记录为 `dry_run` action。
  - live 模式提交 PATCH。
- `INVALID_IMAGE` / `18027` / `100581`
  - 记录 `replace_main_image`，需要人工提供合规主图 URL。
- `QUALIFICATION_REQUIRED` / `18503`
  - 记录 `qualification_or_claim_review`，需要 Seller Central 审批或人工复核并移除 pesticide/antimicrobial 相关宣称。
- 其他问题
  - 记录 `manual_review`。

## 发品前质量闸门

SP-API 新品发品会在提交前运行 `AmazonListingQualityGate`：

- 自动补充 `CABINET` 的 `recommended_uses_for_product=Bathroom`。
- 若本地已有 Product Type Definitions schema 缓存，阻断 schema 标记的必填属性缺失。
- 扫描 title / bullet / description / generic keyword 中的 pesticide/device 高风险宣称，例如 `bacteria`、`antimicrobial`、`disinfect`、`mildew` 等，命中后阻断提交。
- 基于已观测 Amazon issue 阻断 `CABINET` 的 `item_depth_width_height.width > 42in`。
- 检查主图 URL 必须存在且为 HTTPS。
- 对 Giga/B2B 供应商主图给出图片人工复核 warning；如设置 `LISTING_QUALITY_REQUIRE_IMAGE_REVIEW=true`，该 warning 会升级为阻断。

LLM 内容生成后也会使用同类敏感宣称规则输出 validation warning，便于在更早阶段发现风险。

## CLI

```bash
# 默认 dry-run：同步 issue 并生成修复计划
python main.py --task sync-listing-issues

# 真实提交安全自动修复 PATCH
python main.py --task sync-listing-issues --no-dry-run
```

可选环境变量：

```env
LISTING_ISSUE_SYNC_LIMIT=50
LISTING_ISSUE_INCLUDE_SUPPRESSED_REPORT=true
LISTING_QUALITY_REQUIRE_IMAGE_REVIEW=false
```

## 后台定时器

Web server 模式默认不启动定时器。生产需要显式开启：

```env
LISTING_ISSUE_SCHEDULER_ENABLED=true
LISTING_ISSUE_SYNC_INTERVAL_SECONDS=3600
LISTING_ISSUE_REPAIR_DRY_RUN=true
LISTING_ISSUE_INCLUDE_SUPPRESSED_REPORT=true
```

`LISTING_ISSUE_SYNC_INTERVAL_SECONDS` 最小按 300 秒执行，避免过于频繁调用 SP-API。

## 生产前置

Product Type Definitions schema 下载会访问 Amazon 预签 S3 域名，例如 `selling-partner-definitions-prod-iad.s3.amazonaws.com`。若要自动修复缺失属性，需要将该域名加入 ECS `amazon-spapi-proxy.service` allowlist，否则 schema 无法可靠刷新。
