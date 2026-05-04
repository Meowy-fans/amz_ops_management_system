# Giga Sync Services Module Design

## Status

- Contract status: Draft
- Implementation status: Existing behavior documented, no behavior change in this document
- Owner modules:
  - `src/services/giga_sync_service.py`
  - `src/services/giga_price_sync_service.py`
  - `src/services/giga_inventory_sync_service.py`

## Responsibility

The Giga sync services fetch supplier product, price, and inventory data from Giga APIs and persist normalized records locally.

## Services

### `GigaSyncService`

Responsibility: synchronize product detail records.

Main methods:

- `get_full_sku_list(limit_per_page=100, sort=4) -> list[str]`
- `sync_product_details(sku_list, batch_size=50) -> dict[str, int]`
- `sync_full_products() -> dict[str, int]`

Current behavior:

- Reads paginated SKU list from `product_list`.
- Fetches product details from `product_details` in batches.
- Persists via `GigaProductSyncRepository.batch_upsert_products`.
- Commits per successful batch and rolls back failed batches.

### `GigaInventorySyncService`

Responsibility: synchronize supplier inventory.

Main methods:

- `fetch_batch_inventory(skus) -> dict`
- `process_batch(batch_idx, skus) -> tuple[int, int]`
- `sync_all_inventory() -> dict[str, int]`

Current behavior:

- Reads all SKUs from `GigaProductInventoryRepository.get_all_skus`.
- Splits into batches.
- Processes batches through a thread pool.
- Opens one independent DB session per worker batch.
- Returns aggregate stats with total SKUs, batches, processed rows, upserts, and batch counts.

### `GigaPriceSyncService`

Responsibility: synchronize supplier base price tiers.

Current behavior:

- Reads SKUs from price repository.
- Calls Giga API in batches.
- Persists parsed price records.
- Prints progress while also logging.

## External Dependencies

- Giga API client: `infrastructure.giga.api_client.GigaAPIClient`
- Giga credentials and base URL from settings/environment
- PostgreSQL repositories

## Current Deviations To Mitigate

- Service constructors instantiate concrete API clients and repositories directly.
- Some service methods print progress directly, so business logic is coupled to CLI display.
- Inventory sync owns thread-level session creation via global `SessionLocal`, making dependency control harder.
- Retry and rate-limit constants are constructor arguments in inventory sync but partly embedded in product/price sync behavior.
- API response DTOs are implicit dictionaries.

## Acceptance Baseline

- `pytest` must remain green.
- Inventory sync tests must not mock `ThreadPoolExecutor` in a way that blocks `as_completed`.
- Refactors must preserve current batch result shapes and transaction behavior until versioned contracts replace them.
