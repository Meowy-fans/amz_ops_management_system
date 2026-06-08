import pytest

from src.repositories.product_listing_repository import ProductListingRepository


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FetchResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class ExecuteResult:
    def __init__(self, rows=None, scalar_values=None):
        self.rows = rows or []
        self.scalar_values = scalar_values or []

    def scalars(self):
        return ScalarResult(self.scalar_values)

    def fetchall(self):
        return self.rows


class RecordingSession:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if not self.results:
            raise AssertionError("Unexpected execute call")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def last_sql(self):
        return self.calls[-1][0]

    @property
    def last_params(self):
        return self.calls[-1][1]


def _normalized(sql):
    return " ".join(sql.split())


def test_pending_listing_skus_sql_contract_filters_publishability_rules():
    session = RecordingSession([
        ExecuteResult(scalar_values=["MEOW-001", "MEOW-002"]),
    ])
    repo = ProductListingRepository(session)

    result = repo.get_pending_listing_skus()

    sql = _normalized(session.last_sql)
    assert result == ["MEOW-001", "MEOW-002"]
    assert "SELECT DISTINCT m.meow_sku" in sql
    assert "FROM meow_sku_map m" in sql
    assert "amz_all_listing_report" not in sql
    assert "JOIN giga_product_sync_records psr ON m.vendor_sku = psr.giga_sku" in sql
    assert "AND m.vendor_source = 'giga'" in sql
    assert "JOIN giga_product_base_prices pbp ON m.vendor_sku = pbp.giga_sku" in sql
    assert "psr.is_oversize IS NOT TRUE" in sql
    assert "psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'" in sql
    assert "pbp.sku_available IS TRUE" in sql
    assert "ORDER BY m.meow_sku" in sql
    assert session.last_params == {}


def test_variation_data_sql_contract_uses_latest_records_and_cleans_jsonb_values():
    session = RecordingSession([
        ExecuteResult(rows=[
            ("MEOW-A", "GIGA-A", ["GIGA-B"]),
            ("MEOW-B", "GIGA-B", None),
            ("MEOW-C", "GIGA-C", {"unexpected": "shape"}),
        ]),
    ])
    repo = ProductListingRepository(session)

    result = repo.get_variation_data(["MEOW-A", "MEOW-B", "MEOW-C"])

    sql = _normalized(session.last_sql)
    assert result == [
        ("MEOW-A", "GIGA-A", ["GIGA-B"]),
        ("MEOW-B", "GIGA-B", []),
        ("MEOW-C", "GIGA-C", []),
    ]
    assert "WITH latest_records AS" in sql
    assert "ROW_NUMBER() OVER(PARTITION BY giga_sku ORDER BY id DESC) as rn" in sql
    assert "FROM giga_product_sync_records" in sql
    assert "JOIN latest_records lr ON m.vendor_sku = lr.giga_sku" in sql
    assert "WHERE lr.rn = 1" in sql
    assert "m.meow_sku = ANY(:meow_sku_list)" in sql
    assert "COALESCE(lr.raw_data -> 'associateProductList', '[]'::jsonb)" in sql
    assert session.last_params == {"meow_sku_list": ["MEOW-A", "MEOW-B", "MEOW-C"]}


def test_variation_data_empty_input_does_not_hit_database():
    session = RecordingSession([])
    repo = ProductListingRepository(session)

    assert repo.get_variation_data([]) == []
    assert session.calls == []


def test_meow_sku_mapping_by_vendor_skus_sql_contract():
    session = RecordingSession([
        ExecuteResult(rows=[
            ("GIGA-A", "MEOW-A"),
            ("GIGA-B", "MEOW-B"),
        ]),
    ])
    repo = ProductListingRepository(session)

    result = repo.get_meow_skus_by_vendor_skus(["GIGA-A", "GIGA-B"])

    sql = _normalized(session.last_sql)
    assert result == {"GIGA-A": "MEOW-A", "GIGA-B": "MEOW-B"}
    assert "SELECT vendor_sku, meow_sku" in sql
    assert "FROM meow_sku_map" in sql
    assert "WHERE vendor_source = 'giga'" in sql
    assert "vendor_sku = ANY(:vendor_sku_list)" in sql
    assert session.last_params == {"vendor_sku_list": ["GIGA-A", "GIGA-B"]}


def test_meow_sku_mapping_by_vendor_skus_empty_input_does_not_hit_database():
    session = RecordingSession([])
    repo = ProductListingRepository(session)

    assert repo.get_meow_skus_by_vendor_skus([]) == {}
    assert session.calls == []


def test_sku_to_category_mapping_sql_contract_uses_case_insensitive_supplier_mapping():
    session = RecordingSession([
        ExecuteResult(rows=[
            ("MEOW-A", "CABINET"),
            ("MEOW-B", None),
        ]),
    ])
    repo = ProductListingRepository(session)

    result = repo.get_sku_to_category_mapping(["MEOW-A", "MEOW-B"])

    sql = _normalized(session.last_sql)
    assert result == [("MEOW-A", "CABINET"), ("MEOW-B", None)]
    assert "SELECT DISTINCT m.meow_sku, scm.standard_category_name" in sql
    assert "FROM meow_sku_map m" in sql
    assert "JOIN giga_product_sync_records psr ON m.vendor_sku = psr.giga_sku" in sql
    assert "AND m.vendor_source = 'giga'" in sql
    assert "LEFT JOIN supplier_categories_map scm" in sql
    assert "LOWER(psr.category_code) = LOWER(scm.supplier_category_code)" in sql
    assert "scm.supplier_platform = 'giga'" in sql
    assert "WHERE m.meow_sku = ANY(:meow_sku_list)" in sql
    assert "ORDER BY m.meow_sku" in sql
    assert session.last_params == {"meow_sku_list": ["MEOW-A", "MEOW-B"]}


def test_sku_to_category_mapping_empty_input_does_not_hit_database():
    session = RecordingSession([])
    repo = ProductListingRepository(session)

    assert repo.get_sku_to_category_mapping([]) == []
    assert session.calls == []


def test_pending_listing_skus_reraises_database_errors():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = ProductListingRepository(session)

    with pytest.raises(RuntimeError, match="database unavailable"):
        repo.get_pending_listing_skus()
