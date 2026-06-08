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
3. 价格/库存 API 更新的 delayed confirmation
   - 从 `amazon_api_submissions.operation='delayed_confirmation'` 读取每个 SKU 最新一次 `getListingsItem` 响应。
   - 将 `response_body.confirmation.body.issues` 归一化为 `source='price_inventory_confirmation'` 的 open issue。
   - 同一 SKU 最新确认中已消失的 `price_inventory_confirmation` issue 会标记为 `resolved`。

## 数据表

- `amazon_listing_issue_scan_runs`: 每轮扫描记录。
- `amazon_listing_issues`: 当前和历史 issue，按 `sku + marketplace_id + issue_key` 幂等 upsert。
- `amazon_listing_issue_actions`: 修复计划和执行记录。

## 修复策略

默认行为是 dry-run，只生成修复动作，不提交 Amazon 写操作。

当前策略：

- `MISSING_ATTRIBUTE` + `recommended_uses_for_product`
  - 若本地已缓存该 product type schema 且确认属性存在，生成 `patchListingsItem` payload。
  - 第一版只在高置信度时自动计划：`CABINET` / `HOME_MIRROR` 或标题/issue 上下文明确指向 bathroom 时补 `Bathroom`。
  - repair action 的 `request_payload` 会记录 `target_attribute`、`target_value`、`confidence`、`evidence` 和 PATCH payload，方便人工验收。
  - dry-run 记录为 `dry_run` action。
  - live 模式只有 Amazon 返回 `ACCEPTED` 且无 issues 才记录 `submitted`。
- `INVALID_IMAGE` / `18027` / `100581`
  - 记录 `replace_main_image`，需要人工提供合规主图 URL。
- `QUALIFICATION_REQUIRED` / `18503`
  - 记录 `qualification_or_claim_review`，需要 Seller Central 审批或人工复核并移除 pesticide/antimicrobial 相关宣称。
- 其他问题
  - 记录 `manual_review`。

live PATCH 后不会立即判定修复完成。`confirm-listing-issue-repairs` 会在默认 30 分钟后再次调用 `getListingsItem`：

- 原 issue 消失：记录 `confirm_patch_listing_attribute` / `repair_confirmed`，并将 issue 标记为 `resolved`。
- 原 issue 仍存在：记录 `repair_failed`，保留 open issue。
- 确认 API 异常：记录 `repair_confirmation_failed`。

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

# 从价格/库存 delayed confirmation 审计中同步 listing issues，默认 dry-run 生成修复计划
python main.py --task sync-confirmation-listing-issues

# 只针对已入库 open issues 执行修复计划，默认 source=price_inventory_confirmation
python main.py --task repair-listing-issues

# 真实提交推荐属性补全 PATCH
python main.py --task repair-listing-issues --no-dry-run

# 30 分钟后确认已提交的修复动作是否让原 issue 消失
python main.py --task confirm-listing-issue-repairs
```

可选环境变量：

```env
LISTING_ISSUE_SYNC_LIMIT=50
LISTING_ISSUE_INCLUDE_SUPPRESSED_REPORT=true
LISTING_QUALITY_REQUIRE_IMAGE_REVIEW=false
CONFIRMATION_LISTING_ISSUE_SYNC_LIMIT=500
LISTING_ISSUE_REPAIR_SOURCE=price_inventory_confirmation
LISTING_ISSUE_REPAIR_LIMIT=100
LISTING_ISSUE_REPAIR_CONFIRM_AFTER_MINUTES=30
LISTING_ISSUE_REPAIR_CONFIRM_LIMIT=100
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
