# System Architecture

## 1. Overview

The **Amazon Listing Management System** is a full-lifecycle operations platform covering product selection → listing creation → growth → maturity → decline. It integrates with GigaCloud (supplier), Amazon SP-API (listings/pricing/catalog/reports), Amazon Ads API (campaign management), Brand Analytics (search query performance), and multiple LLM providers (DeepSeek/Qwen) for content generation and analysis.

## 2. Architecture Patterns

The system follows a **Layered Architecture** pattern with three new layers added in Phase 1-3:

1.  **Presentation Layer (CLI + Web)**: `main.py` (thin CLI entry), `src/cli/` (menu + task dispatcher + handlers), `scripts/io_server.py` (web dashboard).
2.  **Orchestration Layer** (🆕 Phase 3): `ProductLifecycleManager` (6-stage state machine), `DailyCheckService`, `WeeklyReportService`, `AmazonOrderSyncService`, `AmazonOrderDailyReportService`.
3.  **Service Layer**: 37 business modules covering listing generation, keyword research, competitive intelligence, PPC management, profit analysis, inventory planning, content performance.
4.  **Repository Layer**: 16 data access modules with SQLAlchemy.
5.  **Infrastructure Layer**: SP-API clients (Orders/Listings/Reports/Pricing/Catalog/Ads/Brand Analytics), Giga API, LLM providers, Feishu notifications.
6.  **Reporting Boundary**: `ProgressReporter` for testable output; `FeishuClient` for operational alerts.

### 2.1 Module Dependency Graph

```mermaid
graph TD
    Entry[main.py] --> CLI[src/cli task_dispatcher 40 tasks]
    CLI --> S_Lifecycle[ProductLifecycleManager 🆕]
    CLI --> S_OrderSync[AmazonOrderSyncService]
    CLI --> S_OrderReport[AmazonOrderDailyReportService]
    
    subgraph Orchestration 🆕
        S_Lifecycle --> S_Daily[DailyCheckService]
        S_Lifecycle --> S_Weekly[WeeklyReportService]
        S_Daily --> I_Feishu[FeishuClient]
        S_Weekly --> I_Feishu
        S_OrderSync[AmazonOrderSyncService] --> I_Feishu
        S_OrderReport[AmazonOrderDailyReportService] --> I_Feishu
        S_OrderSync --> I_Orders[AmazonOrdersClient]
    end
    
    subgraph Core Services
        CLI --> S_List[ProductListingService]
        CLI --> S_Sync[GigaSyncService]
        CLI --> S_Price[PricingService]
        CLI --> S_AmazonIssue[AmazonListingIssueSyncService]
        CLI --> S_AmazonSubmit[AmazonListingSubmitter]
        
        S_AmazonSubmit --> S_QualityGate[AmazonListingQualityGate]
        S_AmazonIssue --> S_IssueRepair[AmazonListingIssueRepairService]
        
        S_List --> S_APIPlan[ProductListingAPIPlanBuilder]
        S_APIPlan --> S_Draft[AmazonListingDraftBuilder]
        S_Draft --> S_Content[ProductContentGenerator]
        S_Content --> S_ContentReview[ProductContentReviewer]
        S_APIPlan --> S_Resolver[AttributeResolver]
        S_APIPlan --> S_Variation[AmazonVariationResolver]
    end
    
    subgraph Growth Services 🆕
        CLI --> S_CompIntel[CompetitiveIntelService]
        CLI --> S_PPC[PPCManagementService]
        CLI --> S_Profit[ProfitAnalyzer]
        CLI --> S_Inventory[InventoryPlanner]
        CLI --> S_Review[ReviewSentimentAnalyzer]
        CLI --> S_KWTracker[KeywordRankingTracker]
        CLI --> S_ContentPerf[ContentPerformanceAnalyzer]
        
        S_CompIntel --> I_PricingClient[AmazonPricingClient]
        S_CompIntel --> I_CatalogClient[AmazonCatalogClient]
        S_PPC --> I_AdsClient[AmazonAdsClient]
        S_KWTracker --> I_CatalogClient
    end
    
    subgraph Repositories 16 repos
        S_List --> R_DB[(PostgreSQL)]
        S_Sync --> R_DB
        S_Price --> R_DB
        S_AmazonIssue --> R_DB
    end
    
    subgraph External APIs
        S_Sync --> GigaCloud
        S_List --> LLM[DeepSeek/Qwen]
        S_AmazonIssue --> Amazon[Amazon SP-API]
        S_AmazonSubmit --> Amazon
        I_PricingClient --> Amazon
        I_CatalogClient --> Amazon
        I_AdsClient --> AdsAPI[Amazon Ads API]
        I_BAClient[AmazonBrandAnalyticsClient] --> Amazon
    end
```

## 3. Core Modules

### 3.1 Services (`src/services/`)

| Service | Responsibility |
| :--- | :--- |
| **ProductListingService** | API-native listing orchestration boundary. Coordinates scope filtering, commercial gate, API plan building, submission, and audit logging. |
| **ProductListingAPIPlanBuilder** | Builds API-native listing plans from product data, variation decisions, draft payloads, and pre-submit audit results. |
| **AmazonListingDraftBuilder** | Converts normalized product data into category-aware listing drafts without Excel-like intermediate rows. |
| **ProductContentGenerator / ProductContentReviewer** | Generates product copy and requires deterministic scanner + reviewer LLM approval before content can feed listing. |
| **AttributeRuleLoader / AttributeResolver / AttributePayloadRenderer** | Resolves Amazon attributes through Product Type schema plus YAML rules with evidence/confidence metadata. |
| **AmazonVariationResolver** | Selects variation theme and child attributes using config, historical family data, and fail-closed duplicate checks. |
| **ProductListingScopeFilter** | Applies explicit SKU scope, SKU file scope, local eligibility, category filtering, and optional Amazon existing-listing checks. |
| **ProductListingVariationBuilder** | Deprecated Excel-row variation builder retained for historical reference until the Excel retirement window ends. |
| **template_parser_helpers / template_variation_config / amz_template_rule_correction** | Deprecated Excel-template helpers retained for migration/debugging only. |
| **CategoryMappingCsvUpdater** | Reads, validates, and applies supplier category mapping updates from CSV files. |
| **GigaSyncService** | Synchronizes product details from GigaCloud API to local DB. |
| **PricingService** | Calculates selling prices based on costs and margin rules. |
| **ProductDetailGenerationService** | Uses LLM to generate titles, bullets, and descriptions. |
| **AmazonListingSubmitter** | Submits new listing plans through Listings Items API, preserving dry-run and validation-preview modes. |
| **AmazonListingQualityGate** | Pre-submit listing quality gate; auto-fills safe attributes and blocks known compliance, image, schema, and issue-derived risks before SP-API writes. |
| **AmazonListingIssueSyncService** | Polls official Amazon listing issue sources, including Listings Items issues and FYP suppressed report, then queues repair actions. |
| **AmazonListingIssueRepairService** | Converts synced issues into safe automatic PATCH plans or manual-review actions. |
| **listing_issue_scheduler** | Optional server-mode background scheduler for periodic issue scans; disabled unless explicitly enabled by env. |
| **variation_theme_helpers** | Prepares variation-theme LLM prompts, validates attribute uniqueness, and formats child attributes. |
| **ProgressReporter** | Output boundary used by services to keep CLI display separate from business logic. |

### 3.1.1 CLI Layer (`src/cli/`)

| Module | Responsibility |
| :--- | :--- |
| **menu.py** | Interactive menu display, menu choice mapping, and loop orchestration. |
| **task_dispatcher.py** | Non-interactive task registry and dispatch. |
| **query_handlers.py** | Read-only query commands and display formatting. |
| **category_handlers.py** | Template and category maintenance command handlers. |
| **listing_handlers.py** | Product listing generation command handler. |
| **operation_handlers.py** | Operational sync/import/update command handlers. |

### 3.2 Repositories (`src/repositories/`)

| Repository | Responsibility |
| :--- | :--- |
| **ProductDataRepository** | Read-only access to aggregated product data (Base + LLM + Specs). |
| **ProductListingRepository** | Manages listing status and pending queues. |
| **AmzTemplateRepository** | Deprecated Excel-template repository; API-native listing does not depend on `amazon_cat_templates`. |
| **AmazonListingIssueRepository** | Persists listing issue scan runs, open/resolved issue state, and repair action history. |
| **giga_price_transform** | Pure transforms for Giga price filtering, SKU deduplication, and base/tier row construction before repository persistence. |

### 3.3 Utilities (`src/utils/`)

| Utility | Responsibility |
| :--- | :--- |
| **DataMappingHelper** | Legacy mapper for Excel-era template fields; API-native listing uses draft builders and attribute resolver rules. |
| **DataFieldMapper** | Handles single-field source type mapping, JSONB traversal, unit conversion, and weight calculation. |
| **data_mapping_valid_values / data_mapping_tasks** | Aligns mapped values to Amazon valid values and extracts LLM mapping tasks. |
| **data_mapping_llm** | Builds LLM enrichment requests for Amazon field mapping. |
| **ExcelGenerator** | Deprecated writer for `.xlsm` files; not used by the production new-listing entry. |
| **VariationHelper** | Logic for identifying and grouping variation families. |

## 4. Data Flow: API-native Listing Generation

1.  **Trigger**: Operator runs `generate-listing-api` with a category and optional `--sku`, `--sku-file`, `--only-not-on-amazon`, and `--strict-validation` controls.
2.  **Scope**: `ProductListingScopeFilter` filters pending SKUs by local eligibility, category mapping, explicit SKU scope, and optional read-only Amazon existing-listing checks.
3.  **Commercial Gate**: `AmazonListingCommercialGate` validates price, inventory freshness, margin, currency, zero/negative inventory, and publish quantity cap; over-cap publish quantity is clamped with audit evidence.
4.  **Variation Resolution**: `AmazonVariationResolver` selects parent/child theme and attributes from configuration plus historical family evidence. Duplicate or missing variation signatures fail closed.
5.  **Draft + Content**: `AmazonListingDraftBuilder` builds listing drafts. LLM-generated content must pass deterministic compliance scanning and `ProductContentReviewer` before it can feed API submission.
6.  **Attribute Resolution**: `AttributeResolver` and `AttributePayloadRenderer` add required/recommended structured attributes from Product Type schema and YAML rules with confidence/evidence.
7.  **Quality Gate**: `AmazonListingQualityGate` blocks compliance risks, missing main images, cached-schema gaps, variation payload gaps, and configured issue-derived LIVE risks such as CABINET width over 42in.
8.  **Submit / Preview**: `AmazonListingSubmitter` keeps offline dry-run as default; `--strict-validation` calls Amazon `VALIDATION_PREVIEW` without PUT; `--no-dry-run` is required for LIVE writes.
9.  **Audit**: Results are saved to `amz_listing_log`, `amazon_api_submissions`, commercial gate audit tables, and variation resolution audit tables.

Excel generation is no longer a production new-listing path. Legacy Excel/template modules are marked with `@retire` and governed by `docs/retirement/excel-listing-retirement-2026-06-15.md`.

## 4.1 Data Flow: Listing Issue Monitoring

1.  **Trigger**: User runs `sync-listing-issues` or enables the optional scheduler in server mode.
2.  **Fetch**: `AmazonListingIssueSyncService` calls Listings Items API with `includedData=issues` for local report SKUs.
3.  **Suppressed Report**: The same service optionally requests `GET_MERCHANTS_LISTINGS_FYP_REPORT` through Reports API to capture search-suppressed listing reasons.
4.  **Persist**: `AmazonListingIssueRepository` upserts issue state by `sku + marketplace + issue_key` and marks missing issues resolved.
5.  **Repair Plan**: `AmazonListingIssueRepairService` generates dry-run actions by default. Only schema-confirmed `recommended_uses_for_product` gaps are safe automatic PATCH candidates; image, qualification, pesticide/device, and unknown issues stay in manual review.

## 5. Technology Stack

-   **Language**: Python 3.10+
-   **Database**: PostgreSQL
-   **ORM**: SQLAlchemy 2.0
-   **Data Processing**: Pandas
-   **Excel**: OpenPyXL retained only for legacy migration/debug tooling
-   **AI**: OpenAI API compatible (DeepSeek)

## 6. Deployment Topology

Production deployment follows the server operations contract in `/data/README.md`.

- Source-controlled production compose bundle: `deploy/production/`.
- Runtime compose location: `/data/docker-compose/amz-listing-management-system/`.
- Runtime data location: `/data/volumes/amz-listing-management-system/`.
- Database: shared PostgreSQL container `postgres:5432` on the external Docker `proxy` network, with a dedicated `amz_listing` database/user.
- Secrets: `/data/docker-compose/amz-listing-management-system/.env`; real secrets are not committed.
- Host ports: none. The service joins `proxy`; Traefik exposes `https://amz-listing.meowy.fans` with SSO ForwardAuth as registered in `/data/README.md`.
- Runtime mode: `APP_MODE=server` keeps `scripts/io_server.py` running; one-off CLI tasks run through `docker exec` or `docker compose run --rm`.
- Current production image: `amz-listing-management-system:2026-06-15`.
- Scheduled sidecars in the same compose: `amz-price-inventory-scheduler`, `amz-order-sync-scheduler`, and `amz-order-daily-report-scheduler`.
- Amazon SP-API production traffic must use the configured `AMAZON_HTTPS_PROXY` fixed egress path.
