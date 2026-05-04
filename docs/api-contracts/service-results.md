# Service Result Contracts

## Status

- Contract status: Draft
- Scope: current service return shapes documented for refactor safety
- Compatibility rule: do not break these shapes without a versioned replacement and caller migration

## Listing Generation

Function:

`ProductListingService.generate_listings_by_category(category_name: str) -> dict`

Success:

```json
{
  "success": true,
  "batch_id": "<uuid object or uuid string at caller boundary>",
  "excel_file": "<path>",
  "single_count": 0,
  "variation_count": 0,
  "total_rows": 0,
  "message": "成功生成 N 行数据"
}
```

Failure:

```json
{
  "success": false,
  "message": "<reason>"
}
```

Known failure reasons:

- no pending SKU
- category has no pending SKU
- category has no template rules
- generated row list is empty
- unexpected exception

## Giga Product Detail Sync

Function:

`GigaSyncService.sync_product_details(sku_list: list[str], batch_size: int = 50) -> dict[str, int]`

Return:

```json
{
  "total": 0,
  "success": 0,
  "failed": 0
}
```

## Giga Inventory Sync

Function:

`GigaInventorySyncService.sync_all_inventory() -> dict[str, int]`

Return:

```json
{
  "total_skus": 0,
  "batches": 0,
  "processed": 0,
  "upserted": 0,
  "success_batches": 0,
  "failed_batches": 0
}
```

## Pricing

Function:

`PricingService.update_prices(sku_list: list[str] | None = None) -> tuple[int, int, list[dict]]`

Return tuple:

```python
(total_processed, success_count, report_data)
```

Report row:

```json
{
  "meow_sku": "<sku>",
  "category": "<category or fallback>",
  "purchase_cost": "0.00",
  "logistic_fee": "0.00",
  "total_cost": "0.00",
  "final_price": "0.00",
  "margin": "0.0%"
}
```

## Update File Generation

Function:

`InventoryPriceUpdaterService.generate_update_file() -> None`

Current side effects:

- synchronizes price and inventory data
- recalculates final prices
- writes a tab-separated file under `output/`
- logs and prints status

Target future contract:

```json
{
  "success": true,
  "file_path": "<path>",
  "row_count": 0,
  "warnings": []
}
```

The target future contract is not implemented yet.
