# Pricing And Update File Module Design

## Status

- Contract status: Draft
- Implementation status: Existing behavior documented, no behavior change in this document
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

## Current Deviations To Mitigate

- `PricingService` prints workflow progress directly.
- `InventoryPriceUpdaterService` catches sync errors and continues with existing data. This is current business behavior, but it should be explicit in the API contract and surfaced to callers.
- `generate_update_file()` currently returns `None`; callers must infer success from stdout/logs and generated file side effects.
- Output path is assembled from source file location instead of a configurable output directory.

## Acceptance Baseline

- Existing price calculation tests must remain green.
- Existing CLI task `generate-update-file` must preserve output file format and columns.
- Future refactors should introduce a structured result without breaking the CLI.
