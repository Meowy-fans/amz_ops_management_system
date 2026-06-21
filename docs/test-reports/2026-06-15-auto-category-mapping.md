# Auto Category Mapping Implementation Report

> Date: 2026-06-15  
> Agent: Cursor  
> Requirement: `docs/requirements/auto-category-mapping.md`
> Production Image: `amz-listing-management-system:2026-06-15-auto-category-mapping`

## 1. Scope

Implemented `auto-discover-category`, an automatic Giga category to Amazon
product type mapper based on Catalog Items API reverse lookup.

The implementation uses Amazon Catalog search results as the primary signal:

1. Sample listing-eligible Giga products for a supplier category.
2. Search Amazon Catalog by normalized product/category keywords.
3. Batch fetch ASIN summaries with `includedData=summaries,salesRanks,productTypes`.
4. Vote on `productTypes[].productType`.
5. Write the mapping only when the vote is high confidence and the category is
   still unmapped.
6. Pre-cache the selected Product Type schema after write.

## 2. Code Changes

- Added `CategoryRepository.get_category_sample_products()`.
- Added `CategoryRepository.update_category_mapping_if_unmapped()` to prevent
  overwriting manual mappings.
- Added `AutoCategoryMapper` and `AutoCategoryMappingResult`.
- Added CLI task `auto-discover-category`.
- Added `--category-code` and `--all-unmapped` CLI arguments.
- Updated `AmazonCatalogClient.batch_get_summaries()` to request and parse
  `productTypes[]`; real Catalog API product type is not in `summaries[]`.
- Serialized Catalog identifier batches as comma strings so Amazon returns all
  requested ASINs.

## 3. Validation

Target tests:

```bash
./.venv/bin/pytest -q \
  tests/integration/repositories/test_category_repository_sql_contract.py \
  tests/unit/infrastructure/test_catalog_client.py \
  tests/unit/services/test_auto_category_mapper.py \
  tests/unit/cli/test_task_dispatcher.py \
  tests/integration/cli/test_main_non_interactive_entrypoint.py
```

Result: passed.

Full regression:

```bash
./.venv/bin/pytest -q
git diff --check
```

Result: passed.

Production deployment:

```bash
docker compose -f /data/docker-compose/amz-listing-management-system/docker-compose.yml \
  --env-file /data/docker-compose/amz-listing-management-system/.env build
docker compose -f /data/docker-compose/amz-listing-management-system/docker-compose.yml \
  --env-file /data/docker-compose/amz-listing-management-system/.env up -d --force-recreate
```

Result:

- Production image: `amz-listing-management-system:2026-06-15-auto-category-mapping`
- Main container: healthy.
- `amz-price-inventory-scheduler`, `amz-order-sync-scheduler`, and
  `amz-order-daily-report-scheduler`: running.
- Public route: SSO redirect (`302`).
- `list-categories`: returns `CABINET` / `HOME_MIRROR`.

Production-network dry-run before image rebuild used current source mounted into
a one-off compose container:

```bash
docker compose -f /data/docker-compose/amz-listing-management-system/docker-compose.yml \
  --env-file /data/docker-compose/amz-listing-management-system/.env \
  run --rm --no-deps \
  -v /home/liangqinhao/amz_listing_management_system:/app \
  amz-listing-management-system \
  python main.py --task auto-discover-category --category-code 10027
```

Result:

- Category: `10027 (Sofas)`
- Status: `dry_run_selected`
- Selected product type: `SOFA`
- Catalog votes: `SOFA=5`
- Written: `False`
- Schema cached: `False`

Small no-dry-run smoke:

```bash
docker compose -f /data/docker-compose/amz-listing-management-system/docker-compose.yml \
  --env-file /data/docker-compose/amz-listing-management-system/.env \
  run --rm --no-deps \
  -v /home/liangqinhao/amz_listing_management_system:/app \
  amz-listing-management-system \
  python main.py --task auto-discover-category --category-code 10027 --no-dry-run
```

Result:

- Category: `10027 (Sofas)`
- Status: `mapped`
- Selected product type: `SOFA`
- Catalog votes: `SOFA=5`
- Written: `True`
- Schema cached: `True`

Database verification:

- `supplier_categories_map`: `10027 / Sofas -> SOFA`
- Current unmapped Giga categories: `29`

Post-deploy image smoke:

```bash
docker exec amz-listing-management-system python main.py \
  --task auto-discover-category \
  --category-code 10027
```

Result:

- Category: `10027 (Sofas)`
- Status: `dry_run_selected`
- Selected product type: `SOFA`
- Catalog votes: `SOFA=5`
- Written: `False`
- Schema cached: `False`

## 4. Notes

- `pending-statistics` currently groups non-CABINET/HOME_MIRROR products under
  "其他品类", so it does not directly show the unmapped count reduction.
- `SOFA` is now mapped and schema-cached, but full SOFA listing readiness still
  requires attribute rules / variation strategy validation before LIVE listing.
- The production image was rebuilt and deployed after the initial one-off
  compose validation.
