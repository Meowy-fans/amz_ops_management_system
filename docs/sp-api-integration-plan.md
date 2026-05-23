# Amazon SP-API Integration Plan

## Status

- Planning date: 2026-05-17
- Current state: Amazon private developer / self-use SP-API permission approved. Credentials are stored in the production-only `/data/docker-compose/amz-listing-management-system/.env.amazon-sp-api` file.
- Implementation update: Phase 1 Reports/Listings infrastructure, Phase 2 report sync, Phase 3 price/inventory PATCH path, Phase 4 single-SKU listing API output, and listing issue monitoring are implemented in the repo as of 2026-05-23. Production deployment of the 2026-05-23 changes is still pending.
- Target account type: Amazon Seller Central private application for the user's own store.
- Initial marketplace assumption: US marketplace (`ATVPDKIKX0DER`), NA endpoint.

## Objective

Add a controlled Amazon Selling Partner API integration to the existing Amazon Listing Management System while preserving the current Excel-based workflow as a fallback.

The integration should support:

1. Pulling existing Amazon listing data through Reports API instead of manual file import.
2. Updating existing listing price and inventory through Listings Items API or JSON listings feed.
3. Submitting new listing data through Listings Items API or JSON listings feed after schema validation.
4. Recording Amazon submission status and issues back into the local system.

## Current System Boundary

The current system already has these boundaries:

- Giga product, price, and inventory data are pulled through the Giga API client.
- Amazon listing generation builds mapped rows in `ProductListingService`.
- New listing output is currently written to Amazon `.xlsm` templates through `ExcelGenerator`.
- Price and quantity updates are currently written to tab-separated update files.
- Amazon active listing data is currently imported from manually downloaded report files.

The SP-API work should add a new Amazon API output/input boundary instead of replacing all current file paths immediately.

## Amazon Developer Registration Notes

The user submitted a private developer registration / permission request for self-use. The answer content used for the review described:

- The business sells home products on Amazon US, including bathroom cabinets and mirrors.
- SP-API will be used only for the company's own store operation system.
- Data will be used to sync existing listings, check listing status, generate or update product data from supplier product, price, and inventory data, and submit listing, price, and inventory updates.
- Amazon information will not be shared with external third parties.
- Non-Amazon source data primarily comes from GigaCloud product APIs plus internal SKU mapping, pricing rules, and operational configuration.
- The application will be internal only and will not process buyer personal information.

## Required Amazon Roles

Minimum roles requested / needed:

- `Product Listing`
  - Listings Items API
  - Product Type Definitions API
  - JSON_LISTINGS_FEED
- `Inventory and Order Tracking`
  - Useful for listing and inventory-related read paths where required.

Do not request restricted buyer PII roles for this project unless a future feature explicitly needs them.

## Required Credentials After Approval

After Amazon approves the developer profile and the private app is self-authorized, store these only in production `.env` and never in Git or logs:

```env
AMAZON_LWA_CLIENT_ID=
AMAZON_LWA_CLIENT_SECRET=
AMAZON_REFRESH_TOKEN=
AMAZON_SELLER_ID=
AMAZON_MARKETPLACE_ID=ATVPDKIKX0DER
AMAZON_SP_API_ENDPOINT=https://sellingpartnerapi-na.amazon.com
AMAZON_REGION=NA
AMAZON_HTTPS_PROXY=
```

If roles are changed later, regenerate the refresh token by re-authorizing the private app.

## Network / Egress Requirement

Hard requirement:

- All Amazon API traffic from `amz-listing-management-system` must go through the bastion / Shanghai Aliyun ECS fixed public IP.
- Direct outbound Amazon API calls from the home server or container are not allowed in production.
- The Amazon API client must fail closed when the bastion proxy setting is missing in production.
- Keep all other project traffic on existing routes unless explicitly changed.
- Do not set global `https_proxy` for the whole host or container.
- Add an Amazon-specific client proxy setting such as `AMAZON_HTTPS_PROXY`.

Recommended infrastructure shape:

- Run a restricted HTTP CONNECT or SOCKS proxy on the ECS.
- Bind it to the ECS Tailscale address only, not public `0.0.0.0`.
- Allow access only from the home server Tailscale IP.
- Allow outbound HTTPS only to the needed Amazon endpoints:
  - `api.amazon.com`
  - `sellingpartnerapi-na.amazon.com`
  - `selling-partner-definitions-prod-iad.s3.amazonaws.com` for Product Type Definitions schema documents.
  - Add EU/FE endpoints only if future marketplaces need them.

If this proxy is deployed, update `/data/README.md` and `/data/TODO.md` because it is an infrastructure change.

Implementation implications:

- `AmazonApiClient` must use the Amazon-specific proxy configuration for every request to `api.amazon.com` and `sellingpartnerapi-*.amazon.com`.
- Production config validation should reject missing `AMAZON_HTTPS_PROXY`.
- Smoke tests should verify the observed egress IP is the bastion / ECS IP before any SP-API write operation.
- Do not use global `http_proxy` / `https_proxy` env vars for this requirement; the route must be explicit in the Amazon client or its dedicated transport.

## Implementation Phases

### Phase 1: Amazon API Infrastructure

Add `infrastructure/amazon/`:

- `config.py`: settings and endpoint selection.
- `token_manager.py`: LWA refresh-token to access-token exchange, caching, and expiry handling.
- `api_client.py`: common request wrapper, bastion proxy enforcement, retries, 429 handling, response parsing, request IDs, and token redaction.

Acceptance:

- Completed 2026-05-17.
- Unit tests cover token caching, refresh, 429 retry, secret redaction, and production fail-closed behavior when `AMAZON_HTTPS_PROXY` is missing.
- Bastion proxy smoke confirms only `api.amazon.com:443` and `sellingpartnerapi-na.amazon.com:443` are allowed; `example.com:443` is rejected.
- Production read-only LWA token exchange smoke passed without printing tokens.

### Phase 2: Reports API Read Sync

Replace the manual Amazon full listing report import path with an API-backed path:

- Request `GET_MERCHANT_LISTINGS_ALL_DATA` through Reports API.
- Download the report document.
- Reuse the existing cleaning and repository upsert logic from `AmzFullListImporterService`.

Acceptance:

- Completed 2026-05-17.
- Existing manual file import remains available.
- API sync writes the same target table and statistics shape as file import.
- Production smoke read 418 report rows through Reports API and merged them into `amz_all_listing_report`; resulting statistics: total 445, active 254, unique ASINs 442.
- No credentials or tokens were printed during smoke.

### Phase 3: Price / Inventory API Update

Extend `InventoryPriceUpdaterService` from file generation into submission planning:

- Build a deterministic update plan for SKU, price, and quantity.
- Start with small-batch `patchListingsItem` for existing SKUs.
- Add JSON feed later if batch volume requires it.
- Record submission status and Amazon request IDs.

Acceptance:

- Completed 2026-05-17.
- Dry-run mode shows payloads without submitting.
- Controlled price / quantity PATCH path is available through `update-price-inventory-api`.
- Submission status and issues are persisted in `amazon_api_submissions`.
- Existing tab-separated update file output remains available.

### Phase 4: New Listing API Output

Split listing generation into a plan builder and exporters:

- `ListingPlanBuilder`: build the existing row-level listing plan from Giga, LLM, templates, variations, price, and inventory.
- `ExcelListingExporter`: preserve current `.xlsm` output.
- `AmazonAttributeMapper`: convert local mapped fields to SP-API JSON attributes.
- `AmazonListingSubmitter`: validation preview and submit through Listings Items API.

Important implementation point:

Current fields such as `Item Name`, `Your Price USD (Sell on Amazon, US)`, and `Quantity (US)` are Excel/template labels. SP-API requires JSON attributes that conform to Product Type Definitions schemas. A dedicated mapping layer is required; do not POST Excel field names directly.

Acceptance:

- Completed 2026-05-18 for the Listings Items output path and OTTOMAN end-to-end validation.
- Product Type Definitions schemas are cached per marketplace and product type.
- `VALIDATION_PREVIEW` is available before real new-listing submission.
- `AmazonListingQualityGate` now runs before SP-API submission to block known issue-derived and compliance risks.
- Existing Excel workflow remains the fallback path.

### Phase 4.1: Listing Issue Monitoring and Repair Queue

Add an operational loop for Seller Central listing quality issues:

- `AmazonListingsClient.get_listings_item(... includedData=issues ...)` captures per-SKU listing issues.
- `AmazonListingsClient.search_listings_items(...)` supports issue discovery and manual diagnostics.
- `AmazonReportsClient.create_suppressed_listings_report()` requests `GET_MERCHANTS_LISTINGS_FYP_REPORT`.
- `AmazonListingIssueSyncService` persists current/open/resolved issue state.
- `AmazonListingIssueRepairService` creates dry-run repair actions by default and only live-submits safe, schema-confirmed PATCHes.
- `listing_issue_scheduler` can run the loop in server mode when explicitly enabled.

Acceptance:

- Completed 2026-05-23 in code.
- Official SP-API read paths were validated against current listings: missing `recommended_uses_for_product`, pesticide/device qualification, dimension range warnings, and FYP image suppression can be retrieved.
- `sync-listing-issues` defaults to dry-run and records action plans before any Amazon write.
- Image, qualification, pesticide/device, and unknown issues remain manual-review actions.
- Full test suite passes with 551 tests.

### Phase 5: JSON_LISTINGS_FEED Bulk Submit

Add bulk submit after the single-SKU path is proven:

- Create feed document.
- Upload JSON listings feed.
- Create feed.
- Poll feed processing status.
- Download and parse processing report.
- Persist feed-level and SKU-level issues.

Acceptance:

- Batch submit handles partial failures.
- Feed processing report is linked back to local batch IDs and SKUs.
- Duplicate submissions are avoided by payload hash or idempotency policy.

## Data Model Additions

Proposed tables:

### `amazon_api_submissions`

- `id`
- `batch_id`
- `sku`
- `operation`
- `submission_mode` (`listings_item`, `json_feed`, `reports`)
- `payload_hash`
- `status`
- `amazon_request_id`
- `feed_id`
- `submitted_at`
- `completed_at`
- `raw_response`

### `amazon_api_submission_issues`

- `id`
- `submission_id`
- `sku`
- `issue_code`
- `severity`
- `message`
- `attribute_names`
- `raw_issue`
- `created_at`

### `amazon_product_type_schemas`

- `id`
- `marketplace_id`
- `product_type`
- `requirements`
- `schema_version`
- `schema`
- `retrieved_at`

### Implemented 2026-05-23: `amazon_listing_issue_scan_runs`

- `id`
- `source`
- `status`
- `started_at`
- `finished_at`
- `checked_count`
- `issue_count`
- `action_count`
- `error_message`

### Implemented 2026-05-23: `amazon_listing_issues`

- `id`
- `scan_run_id`
- `sku`
- `asin`
- `marketplace_id`
- `product_type`
- `issue_key`
- `issue_code`
- `severity`
- `message`
- `attribute_names`
- `categories`
- `enforcements`
- `raw_issue`
- `source`
- `status`
- `first_seen_at`
- `last_seen_at`
- `resolved_at`

### Implemented 2026-05-23: `amazon_listing_issue_actions`

- `id`
- `issue_id`
- `scan_run_id`
- `sku`
- `marketplace_id`
- `product_type`
- `action_type`
- `status`
- `reason`
- `request_payload`
- `response_body`
- `error_message`
- `created_at`
- `executed_at`

## Risk Notes

- Amazon role approval is the current external blocker.
- `putListingsItem` is a full replace operation and can drop omitted attributes; use `patchListingsItem` for existing SKU updates where possible.
- Accepted API responses do not guarantee final listing success; asynchronous issues must be retrieved.
- Product Type Definitions requirements can change, so schema retrieval/cache invalidation must be deliberate.
- Product Type Definitions schema document downloads use Amazon pre-signed S3 URLs. The fixed egress proxy allowlist must include the observed definitions host before relying on automatic schema refresh in production.
- New listing API submission is higher risk than price/inventory updates. Implement read sync and existing-SKU updates first.
- Keep tokens and refresh tokens out of logs, source code, and front-end responses.

## Next Actions After Amazon Approval

1. Create the private app and self-authorize it.
2. Store LWA client ID, client secret, refresh token, seller ID, and marketplace ID in production `.env`.
3. Implement Phase 1 Amazon infrastructure with unit tests.
4. Run token exchange smoke.
5. Implement Reports API read sync before any write operations.
