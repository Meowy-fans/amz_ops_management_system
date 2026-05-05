import json

from src.repositories.giga_product_sync_repository import GigaProductSyncRepository


class FetchResult:
    def __init__(self, rows=None, one_row=None):
        self.rows = rows or []
        self.one_row = one_row

    def fetchone(self):
        return self.one_row

    def fetchall(self):
        return self.rows


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


class RecordingBatchRepository(GigaProductSyncRepository):
    def __init__(self, outcomes):
        super().__init__(db=object())
        self.outcomes = list(outcomes)
        self.upsert_calls = []

    def upsert_product(self, giga_sku, raw_data):
        self.upsert_calls.append((giga_sku, raw_data))
        if not self.outcomes:
            raise AssertionError("Unexpected upsert call")
        return self.outcomes.pop(0)


def _normalized(sql):
    return " ".join(sql.split())


def test_upsert_product_sql_contract_serializes_raw_data_and_sets_synced_status():
    session = RecordingSession()
    repo = GigaProductSyncRepository(session)

    raw_data = {
        "sku": "GIGA-1",
        "categoryCode": "CABINET",
        "isOversize": True,
        "name": "商品",
    }

    assert repo.upsert_product("GIGA-1", raw_data) is True

    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "INSERT INTO giga_product_sync_records" in normalized
    assert "CAST(:raw_data AS jsonb)" in normalized
    assert "sync_status, updated_at" in normalized
    assert "ON CONFLICT (giga_sku) DO UPDATE SET" in normalized
    assert "sync_status = 'synced'" in normalized
    assert params["giga_sku"] == "GIGA-1"
    assert params["category_code"] == "CABINET"
    assert params["is_oversize"] is True
    assert json.loads(params["raw_data"]) == raw_data


def test_upsert_product_defaults_missing_category_and_oversize_and_returns_false_on_error():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = GigaProductSyncRepository(session)

    assert repo.upsert_product("GIGA-1", {"sku": "GIGA-1"}) is False

    _, params = session.calls[0]
    assert params["category_code"] is None
    assert params["is_oversize"] is False


def test_batch_upsert_products_skips_missing_sku_and_counts_successes():
    repo = RecordingBatchRepository([True, False, True])
    products = [
        {"sku": "GIGA-1", "name": "Product 1"},
        {"name": "Missing SKU"},
        {"sku": "GIGA-2", "name": "Product 2"},
        {"sku": "GIGA-3", "name": "Product 3"},
    ]

    assert repo.batch_upsert_products(products) == 2
    assert repo.upsert_calls == [
        ("GIGA-1", products[0]),
        ("GIGA-2", products[2]),
        ("GIGA-3", products[3]),
    ]


def test_get_product_by_sku_sql_contract_maps_row_to_dict():
    raw_data = {"sku": "GIGA-1", "name": "Product 1"}
    session = RecordingSession([
        FetchResult(one_row=("GIGA-1", "CABINET", False, raw_data, "synced")),
    ])
    repo = GigaProductSyncRepository(session)

    assert repo.get_product_by_sku("GIGA-1") == {
        "giga_sku": "GIGA-1",
        "category_code": "CABINET",
        "is_oversize": False,
        "raw_data": raw_data,
        "sync_status": "synced",
    }
    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "SELECT giga_sku, category_code, is_oversize, raw_data, sync_status" in normalized
    assert "FROM giga_product_sync_records" in normalized
    assert "WHERE giga_sku = :giga_sku" in normalized
    assert params == {"giga_sku": "GIGA-1"}


def test_get_product_by_sku_returns_none_for_missing_row_or_database_error():
    missing_session = RecordingSession([FetchResult(one_row=None)])
    error_session = RecordingSession([RuntimeError("database unavailable")])

    assert GigaProductSyncRepository(missing_session).get_product_by_sku("GIGA-1") is None
    assert GigaProductSyncRepository(error_session).get_product_by_sku("GIGA-1") is None


def test_get_statistics_sql_contract_counts_total_synced_and_oversize():
    session = RecordingSession([
        FetchResult(one_row=(10, 8, 2)),
    ])
    repo = GigaProductSyncRepository(session)

    assert repo.get_statistics() == {"total": 10, "synced": 8, "oversize": 2}
    sql = _normalized(session.calls[0][0])
    assert "COUNT(*) as total" in sql
    assert "COUNT(*) FILTER (WHERE sync_status = 'synced') as synced" in sql
    assert "COUNT(*) FILTER (WHERE is_oversize = true) as oversize" in sql
    assert "FROM giga_product_sync_records" in sql


def test_get_statistics_returns_zero_counts_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = GigaProductSyncRepository(session)

    assert repo.get_statistics() == {"total": 0, "synced": 0, "oversize": 0}


def test_get_all_skus_sql_contract_orders_by_id():
    session = RecordingSession([
        FetchResult(rows=[("GIGA-1",), ("GIGA-2",)]),
    ])
    repo = GigaProductSyncRepository(session)

    assert repo.get_all_skus() == ["GIGA-1", "GIGA-2"]
    assert _normalized(session.calls[0][0]) == (
        "SELECT giga_sku FROM giga_product_sync_records ORDER BY id"
    )


def test_get_all_skus_returns_empty_list_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = GigaProductSyncRepository(session)

    assert repo.get_all_skus() == []
