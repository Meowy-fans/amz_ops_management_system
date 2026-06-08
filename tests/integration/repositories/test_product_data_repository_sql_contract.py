import pytest

from src.repositories.product_data_repository import ProductDataRepository


class MappingResult:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row


class FetchResult:
    def __init__(self, mapping_row=None):
        self.mapping_row = mapping_row

    def mappings(self):
        return MappingResult(self.mapping_row)


class RecordingSession:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return FetchResult()


def _normalized(sql):
    return " ".join(sql.split())


def test_get_full_product_data_sql_contract_returns_mapping_dict():
    row = {
        "meow_sku": "M001",
        "vendor_sku": "GIGA-1",
        "category_name": "CABINET",
        "product_name": "Cabinet",
        "product_description": "Description",
        "selling_point_1": "Point 1",
        "selling_point_2": "Point 2",
        "selling_point_3": "Point 3",
        "selling_point_4": "Point 4",
        "selling_point_5": "Point 5",
        "raw_data": {"category_code": "CAB001"},
        "final_price": 199.99,
        "price_currency": "USD",
        "cost_at_pricing": 120.00,
        "pricing_formula_version": "v1",
        "price_updated_at": "2026-06-08T00:00:00Z",
        "inventory_quantity": 12,
        "buyer_qty": 5,
        "seller_qty": 0,
        "inventory_last_updated": "2026-06-08T01:00:00Z",
        "total_quantity": 12,
    }
    session = RecordingSession([FetchResult(mapping_row=row)])
    repository = ProductDataRepository(session)

    product_data = repository.get_full_product_data("M001")

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert product_data == row
    assert "FROM meow_sku_map m" in normalized_sql
    assert "LEFT JOIN ds_api_product_details ds ON m.vendor_sku = ds.sku_id" in (
        normalized_sql
    )
    assert "LEFT JOIN giga_product_sync_records psr ON m.vendor_sku = psr.giga_sku" in (
        normalized_sql
    )
    assert "LEFT JOIN supplier_categories_map scm" in normalized_sql
    assert "LOWER(psr.category_code) = LOWER(scm.supplier_category_code)" in (
        normalized_sql
    )
    assert "LEFT JOIN product_final_prices pfp ON m.meow_sku = pfp.meow_sku" in (
        normalized_sql
    )
    assert "LEFT JOIN giga_inventory inv ON m.vendor_sku = inv.giga_sku" in (
        normalized_sql
    )
    assert "pfp.currency AS price_currency" in normalized_sql
    assert "pfp.cost_at_pricing" in normalized_sql
    assert "pfp.pricing_formula_version" in normalized_sql
    assert "pfp.updated_at AS price_updated_at" in normalized_sql
    assert "COALESCE(inv.quantity, 0) AS inventory_quantity" in normalized_sql
    assert "COALESCE(inv.buyer_qty, 0) AS buyer_qty" in normalized_sql
    assert "COALESCE(inv.seller_qty, 0) AS seller_qty" in normalized_sql
    assert "inv.last_updated AS inventory_last_updated" in normalized_sql
    assert "COALESCE(inv.quantity, 0) AS total_quantity" in normalized_sql
    assert "WHERE m.meow_sku = :meow_sku" in normalized_sql
    assert "ORDER BY psr.id DESC, ds.id DESC LIMIT 1" in normalized_sql
    assert params == {"meow_sku": "M001"}


def test_get_full_product_data_returns_empty_dict_when_missing():
    session = RecordingSession([FetchResult(mapping_row=None)])
    repository = ProductDataRepository(session)

    assert repository.get_full_product_data("MISSING") == {}


def test_get_full_product_data_reraises_database_errors():
    session = RecordingSession([RuntimeError("select failed")])
    repository = ProductDataRepository(session)

    with pytest.raises(RuntimeError, match="select failed"):
        repository.get_full_product_data("M001")
