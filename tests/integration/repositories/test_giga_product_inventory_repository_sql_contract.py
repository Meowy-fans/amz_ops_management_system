import json

import pytest

from src.repositories.giga_product_inventory_repository import (
    GigaProductInventoryRepository,
)


class FetchResult:
    def __init__(self, rows=None, one_row=None):
        self.rows = rows or []
        self.one_row = one_row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one_row


class RecordingSession:
    def __init__(self, results=None, connection=None):
        self.results = list(results or [])
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
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

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.copy_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql):
        self.executed.append(" ".join(sql.split()))

    def copy_expert(self, sql, file):
        self.copy_calls.append((sql, file.read()))


class FailingCursor(FakeCursor):
    def copy_expert(self, sql, file):
        raise RuntimeError("copy failed")


class FakeRawConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class FakeConnection:
    def __init__(self, cursor):
        self.connection = FakeRawConnection(cursor)


def _normalized(sql):
    return " ".join(sql.split())


def _inventory_row(giga_sku="GIGA-1"):
    return {
        "giga_sku": giga_sku,
        "quantity": 12,
        "buyer_qty": 7,
        "buyer_partner_qty": 2,
        "seller_qty": 3,
        "buyer_distribution": '[{"warehouse":"A","qty":7}]',
        "seller_distribution": '[{"warehouse":"B","qty":3}]',
        "next_arrival_date": "2026-01-10",
        "next_arrival_date_end": "2026-01-15",
        "next_arrival_qty": 20,
        "next_arrival_qty_max": 25,
        "last_updated": "2026-05-05 14:30:00",
    }


def test_get_all_skus_sql_contract_returns_sorted_distinct_skus():
    session = RecordingSession([
        FetchResult(rows=[("GIGA-1",), ("GIGA-2",)]),
    ])
    repo = GigaProductInventoryRepository(session)

    assert repo.get_all_skus() == ["GIGA-1", "GIGA-2"]
    sql = _normalized(session.calls[0][0])
    assert "SELECT DISTINCT giga_sku" in sql
    assert "FROM giga_product_sync_records" in sql
    assert "WHERE giga_sku IS NOT NULL" in sql
    assert "ORDER BY giga_sku" in sql
    assert session.calls[0][1] == {}


def test_get_all_skus_returns_empty_list_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = GigaProductInventoryRepository(session)

    assert repo.get_all_skus() == []


def test_parse_inventory_item_maps_nested_quantities_and_next_arrival():
    repo = GigaProductInventoryRepository(db=object())

    result = repo.parse_inventory_item({
        "sku": "GIGA-1",
        "quantity": 12,
        "qtyDetail": {
            "buyerQty": 7,
            "buyerPartnerQty": 2,
            "sellerQty": 3,
            "buyerQtyDistribution": [{"warehouse": "A", "qty": 7}],
            "sellerQtyDistribution": [{"warehouse": "B", "qty": 3}],
        },
        "nextArrival": {
            "nextArrivalDate": "2026-01-10",
            "nextArrivalDateEnd": "2026-01-15",
            "nextArrivalQty": 20,
            "nextArrivalQtyMax": 25,
        },
    })

    assert result["giga_sku"] == "GIGA-1"
    assert result["quantity"] == 12
    assert result["buyer_qty"] == 7
    assert result["buyer_partner_qty"] == 2
    assert result["seller_qty"] == 3
    assert json.loads(result["buyer_distribution"]) == [{"warehouse": "A", "qty": 7}]
    assert json.loads(result["seller_distribution"]) == [{"warehouse": "B", "qty": 3}]
    assert result["next_arrival_date"] == "2026-01-10"
    assert result["next_arrival_date_end"] == "2026-01-15"
    assert result["next_arrival_qty"] == 20
    assert result["next_arrival_qty_max"] == 25
    assert result["last_updated"]


def test_parse_inventory_item_defaults_missing_values_and_clears_zero_seller_distribution():
    repo = GigaProductInventoryRepository(db=object())

    result = repo.parse_inventory_item({
        "qtyDetail": {
            "sellerQty": 0,
            "sellerQtyDistribution": [{"warehouse": "B", "qty": 3}],
        },
    })

    assert result["giga_sku"] == "UNKNOWN_SKU"
    assert result["quantity"] == 0
    assert result["buyer_qty"] == 0
    assert result["buyer_partner_qty"] == 0
    assert result["seller_qty"] == 0
    assert json.loads(result["buyer_distribution"]) == []
    assert json.loads(result["seller_distribution"]) == []
    assert result["next_arrival_date"] == "1970-01-01"
    assert result["next_arrival_date_end"] == "1970-01-01"
    assert result["next_arrival_qty"] == 0
    assert result["next_arrival_qty_max"] == 0


def test_parse_inventory_item_reraises_unexpected_input_errors():
    class BrokenItem:
        def get(self, key, default=None):
            raise RuntimeError("bad inventory payload")

    repo = GigaProductInventoryRepository(db=object())

    with pytest.raises(RuntimeError, match="bad inventory payload"):
        repo.parse_inventory_item(BrokenItem())


def test_bulk_upsert_inventory_empty_input_short_circuits_without_connection():
    session = RecordingSession(connection=None)
    repo = GigaProductInventoryRepository(session)

    assert repo.bulk_upsert_inventory([]) == (0, 0)
    assert session.commits == 0
    assert session.rollbacks == 0


def test_bulk_upsert_inventory_uses_temp_table_copy_upsert_and_commits():
    cursor = FakeCursor()
    session = RecordingSession(connection=FakeConnection(cursor))
    repo = GigaProductInventoryRepository(session)

    assert repo.bulk_upsert_inventory([
        _inventory_row("GIGA-1"),
        _inventory_row("GIGA-2"),
    ]) == (2, 2)

    assert len(cursor.executed) == 2
    assert "CREATE TEMP TABLE tmp_inventory" in cursor.executed[0]
    assert "LIKE giga_inventory" in cursor.executed[0]
    assert "ON COMMIT DROP" in cursor.executed[0]
    assert "INSERT INTO giga_inventory SELECT * FROM tmp_inventory" in cursor.executed[1]
    assert "ON CONFLICT (giga_sku) DO UPDATE SET" in cursor.executed[1]
    assert "quantity = EXCLUDED.quantity" in cursor.executed[1]
    assert "last_updated = EXCLUDED.last_updated" in cursor.executed[1]
    assert len(cursor.copy_calls) == 1
    copy_sql, payload = cursor.copy_calls[0]
    assert copy_sql == "COPY tmp_inventory FROM STDIN WITH CSV"
    assert "GIGA-1,12,7,2,3" in payload
    assert "GIGA-2,12,7,2,3" in payload
    assert session.commits == 1
    assert session.rollbacks == 0


def test_bulk_upsert_inventory_rolls_back_and_returns_zero_success_when_copy_fails():
    session = RecordingSession(connection=FakeConnection(FailingCursor()))
    repo = GigaProductInventoryRepository(session)

    assert repo.bulk_upsert_inventory([_inventory_row()]) == (1, 0)
    assert session.commits == 0
    assert session.rollbacks == 1


def test_get_statistics_sql_contract_counts_inventory_totals():
    session = RecordingSession([
        FetchResult(one_row=(7, 5, 42)),
    ])
    repo = GigaProductInventoryRepository(session)

    assert repo.get_statistics() == {
        "total_skus": 7,
        "in_stock_skus": 5,
        "total_quantity": 42,
    }
    sql = _normalized(session.calls[0][0])
    assert "COUNT(*) as total" in sql
    assert "COUNT(*) FILTER (WHERE quantity > 0) as in_stock" in sql
    assert "SUM(quantity) as total_quantity" in sql
    assert "FROM giga_inventory" in sql


def test_get_statistics_returns_zero_counts_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = GigaProductInventoryRepository(session)

    assert repo.get_statistics() == {
        "total_skus": 0,
        "in_stock_skus": 0,
        "total_quantity": 0,
    }
