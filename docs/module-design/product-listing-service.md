# ProductListingService Module Design

## Status

- Contract status: Draft
- Implementation status: Existing behavior documented, no behavior change in this document
- Owner module: `src/services/product_listing_service.py`

## Responsibility

`ProductListingService` generates Amazon listing upload workbooks for one Amazon category.

## Current Collaborators

- `ProductListingRepository`: pending SKU discovery, SKU category mapping, variation relation data.
- `ProductDataRepository`: full product data for one `meow_sku`.
- `AmzTemplateRepository`: latest Amazon template rules for a category.
- `AmzListingLogRepository`: generated listing log persistence.
- `DataMappingHelper`: local product data to Amazon template field mapping.
- `ExcelGenerator`: `.xlsm` file generation.
- `VariationHelper`: connected-component grouping of variation families.
- Optional LLM service: initialized inside the service constructor.
- Optional `VariationThemeService`: initialized inside the service constructor.

## Main Flow

1. Create `batch_id`.
2. Load all pending `meow_sku` values.
3. Resolve `meow_sku -> standard_category_name`.
4. Filter SKUs by requested category, case-insensitive.
5. Load variation relation data.
6. Split SKUs into singles and variation families.
7. Load Amazon category template rules.
8. Process singles into template rows.
9. Process variation families into parent/child rows and log entries.
10. Generate an Excel upload workbook.
11. Save listing logs and commit the DB transaction.

## Inputs

`generate_listings_by_category(category_name: str)`.

Constraints:

- `category_name` must match `standard_category_name` from supplier category mapping.
- The category must have a template in `amazon_cat_templates`.
- Template workbook must exist under `template_files/` for the generated category.
- Product data must include enough LLM detail, price, inventory, and raw Giga fields for field mapping.

## Outputs

Success:

```python
{
    "success": True,
    "batch_id": UUID,
    "excel_file": str,
    "single_count": int,
    "variation_count": int,
    "total_rows": int,
    "message": str,
}
```

Failure:

```python
{
    "success": False,
    "message": str,
}
```

## Data Dependencies

- `meow_sku_map`
- `giga_product_sync_records`
- `supplier_categories_map`
- `ds_api_product_details`
- `product_final_prices`
- `giga_inventory`
- `giga_product_base_prices`
- `amz_all_listing_report`
- `amazon_cat_templates`
- `amz_listing_log`

## Current Deviations To Mitigate

- The constructor creates concrete repositories and helpers directly, which makes dependency replacement patch-heavy.
- Optional LLM and variation theme dependencies are initialized dynamically in the constructor.
- Return shape is an untyped dict instead of a declared DTO.
- The service owns transaction commit/rollback. That is current behavior, but future application-service boundaries should make transaction ownership explicit.
- Core method is broad and delegates to private helpers, but the file is 500 lines and exceeds the project guideline threshold.

## Acceptance Baseline

- Existing CLI command `python main.py --task generate-listing --category <CATEGORY>` must keep the same observable behavior.
- Existing unit tests for `ProductListingService` must pass.
- Future refactors must preserve the success/failure dict contract until a versioned contract replaces it.
