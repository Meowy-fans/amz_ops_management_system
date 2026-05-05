from decimal import Decimal

from src.repositories.giga_product_price_repository import GigaProductPriceRepository


class FetchResult:
    def __init__(self, rows=None, scalar_value=None, one_row=None):
        self.rows = rows or []
        self.scalar_value = scalar_value
        self.one_row = one_row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one_row

    def scalar(self):
        return self.scalar_value


class RecordingSession:
    def __init__(self, results=None, connection=None):
        self.results = list(results or [])
        self.calls = []
        self._connection = connection

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if not self.results:
            raise AssertionError("Unexpected execute call")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def connection(self):
        return self._connection


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.copy_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def copy_expert(self, sql, file):
        self.copy_calls.append((sql, file.read()))


class FakeRawConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class FakeConnection:
    def __init__(self, cursor):
        self.connection = FakeRawConnection(cursor)


class FailingBasePriceRepository(GigaProductPriceRepository):
    def _bulk_upsert_base_prices(self, data):
        raise RuntimeError("base write failed")


class RecordingBulkRepository(GigaProductPriceRepository):
    def __init__(self):
        super().__init__(db=object())
        self.base_batches = []
        self.tier_batches = []

    def _bulk_upsert_base_prices(self, data):
        self.base_batches.append(data)

    def _bulk_upsert_tier_prices(self, data):
        self.tier_batches.append(data)


class FailingTierRepository(RecordingBulkRepository):
    def _bulk_upsert_tier_prices(self, data):
        raise RuntimeError("tier write failed")


def _normalized(sql):
    return " ".join(sql.split())


def _base_price_row(giga_sku="GIGA-1"):
    return {
        "giga_sku": giga_sku,
        "currency": "USD",
        "base_price": Decimal("20.00"),
        "shipping_fee": Decimal("4.50"),
        "shipping_fee_min": Decimal("3.00"),
        "shipping_fee_max": Decimal("6.00"),
        "exclusive_price": Decimal("18.00"),
        "discounted_price": Decimal("17.50"),
        "promotion_start": "2026-01-01T00:00:00Z",
        "promotion_end": "2026-02-01T00:00:00Z",
        "map_price": Decimal("22.00"),
        "future_map_price": Decimal("24.00"),
        "effect_map_time": "2026-03-01T00:00:00Z",
        "sku_available": True,
        "seller_info": '{"seller":"giga"}',
        "full_response": '{"sku":"GIGA-1"}',
    }


def _tier_price_row(giga_sku="GIGA-1"):
    return {
        "giga_sku": giga_sku,
        "tier_type": "base",
        "min_quantity": 1,
        "max_quantity": 5,
        "price": Decimal("20.00"),
        "discounted_price": Decimal("18.00"),
        "effective_date": "2026-01-01T00:00:00Z",
    }


def test_get_all_skus_sql_contract_returns_sorted_distinct_skus():
    session = RecordingSession([
        FetchResult(rows=[("GIGA-1",), ("GIGA-2",)]),
    ])
    repo = GigaProductPriceRepository(session)

    assert repo.get_all_skus() == ["GIGA-1", "GIGA-2"]
    sql = _normalized(session.calls[0][0])
    assert "SELECT DISTINCT giga_sku" in sql
    assert "FROM giga_product_sync_records" in sql
    assert "WHERE giga_sku IS NOT NULL" in sql
    assert "ORDER BY giga_sku" in sql
    assert session.calls[0][1] == {}


def test_get_all_skus_returns_empty_list_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = GigaProductPriceRepository(session)

    assert repo.get_all_skus() == []


def test_bulk_upsert_base_prices_uses_temp_table_copy_and_conflict_update():
    cursor = FakeCursor()
    repo = GigaProductPriceRepository(RecordingSession(connection=FakeConnection(cursor)))

    repo._bulk_upsert_base_prices([_base_price_row()])

    assert len(cursor.executed) == 2
    assert "CREATE TEMP TABLE tmp_base_prices" in cursor.executed[0][0]
    assert "ON COMMIT DROP" in cursor.executed[0][0]
    assert "INSERT INTO giga_product_base_prices" in cursor.executed[1][0]
    assert "ON CONFLICT (giga_sku) DO UPDATE SET" in cursor.executed[1][0]
    assert len(cursor.copy_calls) == 1
    copy_sql, payload = cursor.copy_calls[0]
    assert copy_sql == "COPY tmp_base_prices FROM STDIN WITH CSV"
    assert "GIGA-1,USD,20.00,4.50,3.00,6.00,18.00,17.50" in payload


def test_bulk_upsert_tier_prices_deletes_old_tiers_and_inserts_new_rows():
    cursor = FakeCursor()
    repo = GigaProductPriceRepository(RecordingSession(connection=FakeConnection(cursor)))

    repo._bulk_upsert_tier_prices([
        _tier_price_row("GIGA-1"),
        _tier_price_row("GIGA-2"),
    ])

    assert len(cursor.executed) == 3
    delete_sql, delete_params = cursor.executed[0]
    assert "DELETE FROM giga_price_tiers" in delete_sql
    assert "WHERE giga_sku = ANY(%s)" in delete_sql
    assert set(delete_params[0]) == {"GIGA-1", "GIGA-2"}
    assert "CREATE TEMP TABLE tmp_tier_prices" in cursor.executed[1][0]
    assert "INSERT INTO giga_price_tiers" in cursor.executed[2][0]
    assert "INNER JOIN giga_product_base_prices bp ON bp.giga_sku = tmp.giga_sku" in cursor.executed[2][0]
    assert len(cursor.copy_calls) == 1
    copy_sql, payload = cursor.copy_calls[0]
    assert copy_sql == "COPY tmp_tier_prices FROM STDIN WITH CSV"
    assert "GIGA-1,base,1,5,20.00,18.00" in payload
    assert "GIGA-2,base,1,5,20.00,18.00" in payload


def test_batch_upsert_prices_short_circuits_empty_input():
    repo = RecordingBulkRepository()

    assert repo.batch_upsert_prices([]) == (0, 0)
    assert repo.base_batches == []
    assert repo.tier_batches == []


def test_batch_upsert_prices_writes_prepared_base_and_tier_rows():
    repo = RecordingBulkRepository()

    success_count, failed_count = repo.batch_upsert_prices([
        {
            "sku": "GIGA-1",
            "currency": "USD",
            "price": "20.00",
            "shippingFee": "4.50",
            "skuAvailable": True,
            "sellerInfo": {"seller": "giga"},
            "spotPrice": [
                {
                    "minQuantity": 1,
                    "maxQuantity": 5,
                    "price": "20.00",
                    "discountedPrice": "18.00",
                    "effectiveDate": "2026-01-01T00:00:00Z",
                }
            ],
        }
    ])

    assert (success_count, failed_count) == (1, 0)
    assert repo.base_batches[0][0]["giga_sku"] == "GIGA-1"
    assert repo.tier_batches[0][0]["giga_sku"] == "GIGA-1"


def test_batch_upsert_prices_reports_failed_count_when_base_write_fails():
    repo = FailingBasePriceRepository(db=object())

    assert repo.batch_upsert_prices([
        {
            "sku": "GIGA-1",
            "currency": "USD",
            "price": "20.00",
            "skuAvailable": True,
        }
    ]) == (0, 1)


def test_batch_upsert_prices_keeps_success_when_tier_write_fails():
    repo = FailingTierRepository()

    assert repo.batch_upsert_prices([
        {
            "sku": "GIGA-1",
            "currency": "USD",
            "price": "20.00",
            "skuAvailable": True,
            "spotPrice": [
                {
                    "minQuantity": 1,
                    "maxQuantity": 5,
                    "price": "20.00",
                }
            ],
        }
    ]) == (1, 0)
    assert repo.base_batches[0][0]["giga_sku"] == "GIGA-1"


def test_bulk_upsert_tier_prices_empty_input_does_not_open_connection():
    session = RecordingSession(connection=None)
    repo = GigaProductPriceRepository(session)

    repo._bulk_upsert_tier_prices([])

    assert session.calls == []


def test_parse_datetime_returns_none_for_empty_and_invalid_values():
    repo = GigaProductPriceRepository(db=object())

    assert repo._parse_datetime(None) is None
    assert repo._parse_datetime("") is None
    assert repo._parse_datetime("not-a-date") is None


def test_parse_datetime_returns_datetime_for_iso_values():
    repo = GigaProductPriceRepository(db=object())

    assert repo._parse_datetime("2026-01-01T00:00:00Z").year == 2026


def test_get_statistics_sql_contract_counts_base_prices_and_tiers():
    session = RecordingSession([
        FetchResult(one_row=(7, 5, 2)),
        FetchResult(scalar_value=11),
    ])
    repo = GigaProductPriceRepository(session)

    assert repo.get_statistics() == {
        "total_prices": 7,
        "available_skus": 5,
        "currencies": 2,
        "total_tiers": 11,
    }
    assert "FROM giga_product_base_prices" in _normalized(session.calls[0][0])
    assert _normalized(session.calls[1][0]) == "SELECT COUNT(*) FROM giga_price_tiers"


def test_get_statistics_returns_zero_counts_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = GigaProductPriceRepository(session)

    assert repo.get_statistics() == {
        "total_prices": 0,
        "available_skus": 0,
        "currencies": 0,
        "total_tiers": 0,
    }
