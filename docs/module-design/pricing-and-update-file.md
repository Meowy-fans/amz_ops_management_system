# Pricing And Update File Module Design

## Status

- Contract status: Draft
- Implementation status: API update path is API-native; file path remains legacy
- Owner modules:
  - `src/services/pricing_service.py`
  - `src/services/amz_inventory_price_updater_service.py`

## Responsibility

Pricing modules calculate final Amazon selling prices and generate Amazon price/quantity update files.

## `PricingService`

Responsibility: calculate and persist final prices for selected or all `meow_sku` values.

Main method:

`update_prices(sku_list: list[str] | None = None) -> tuple[int, int, list[dict]]`

Flow:

1. Load target SKU list, either passed by caller or from `PricingRepository.get_all_meow_skus`.
2. Categorize SKUs through `CategoryService`.
3. Load purchase cost and logistic fee from `PricingRepository.get_costs_for_skus`.
4. Resolve pricing parameters by category through `PricingConfigLoader`.
5. Calculate final price using:

```text
price = (pc + lf) * (1 + logistic_protection_rate + return_rate)
        / (1 - commission_rate - ad_cost_rate - settlement_cost_rate - target_margin_rate)
```

6. Persist final prices through `PricingRepository.upsert_final_prices`.

Return tuple:

- total processed SKU count
- successfully priced SKU count
- report rows for display/export

## `InventoryPriceUpdaterService`

Responsibility: generate Amazon inventory and price update `.txt` file.

Flow:

1. Synchronize Giga price data.
2. Synchronize Giga inventory data.
3. Recalculate system final prices.
4. Load Amazon-to-Giga SKU mappings from `ListingDataRepository`.
5. Load latest price and inventory data.
6. Emit tab-separated file under `output/`.

Output columns:

- `sku`
- `price`
- `minimum-seller-allowed-price`
- `maximum-seller-allowed-price`
- `quantity`
- `handling-time`
- `fulfillment-channel`

## API-Native Price/Inventory Update

Entry point: `InventoryPriceUpdaterService.submit_updates_via_api()`

Implementation owner: `AmazonPriceInventoryUpdateService`

The API path no longer uses `amz_all_listing_report` as the candidate source.
It uses Listings Items API as the Amazon fact source:

1. Refresh `amazon_listing_items_cache` through `searchListingsItems`.
2. Select mapped SKUs from `amazon_listing_items_cache` joined to `meow_sku_map`.
3. Load local target price from `product_final_prices`.
4. Load local target quantity from `giga_inventory.quantity`.
5. Call `getListingsItem` before patching each SKU.
6. Block listings with ERROR issues.
7. Skip SKUs whose Amazon price and quantity already match local targets.
8. Use `patchListingsItem` for changed `purchasable_offer` and/or `fulfillment_availability`.
9. Parse PATCH response status and issues.
10. Confirm accepted updates with a second `getListingsItem` and compare target values.

Submission statuses:

- `dry_run`
- `skipped_no_change`
- `skipped_not_found`
- `blocked_listing_issue`
- `issues_found`
- `not_accepted`
- `update_confirmed`
- `confirmed_with_mismatch`
- `confirmed_with_issues`
- `accepted_pending_confirmation`
- `confirmation_failed`
- `failed`

Delayed confirmation statuses:

- `delayed_update_confirmed`
- `delayed_confirmed_with_mismatch`
- `delayed_confirmed_with_issues`
- `delayed_confirmed_with_issues_and_mismatch`
- `delayed_confirmation_failed`

`confirm-price-inventory-api` re-checks accepted but not fully verified submissions
after `PRICE_INVENTORY_CONFIRM_AFTER_MINUTES` minutes, default 30. It writes a
new `amazon_api_submissions` row with operation `delayed_confirmation` and
links to the original row through `response_body.source_submission_id`; it does
not PATCH Amazon. Production scheduler runs this delayed confirmation before
starting the next hourly update.

The legacy file generation path still exists for manual fallback and continues to
use its existing output format.

## Current Deviations To Mitigate

- `PricingService` prints workflow progress directly.
- `InventoryPriceUpdaterService` catches sync errors and continues with existing data. This is current business behavior, but it should be explicit in the API contract and surfaced to callers.
- API path performs Amazon read calls even in dry-run mode because candidate data is API-native; dry-run only suppresses PATCH writes.
- `generate_update_file()` currently returns `None`; callers must infer success from stdout/logs and generated file side effects.
- Output path is assembled from source file location instead of a configurable output directory.

## Acceptance Baseline

- Existing price calculation tests must remain green.
- Existing CLI task `generate-update-file` must preserve output file format and columns.
- Future refactors should introduce a structured result without breaking the CLI.
