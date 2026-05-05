from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.repositories.pricing_repository import PricingRepository


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
        self.executed_sql = []
        self.copy_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql):
        self.executed_sql.append(" ".join(sql.split()))

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


def test_get_all_meow_skus_sql_contract_returns_scalar_list():
    session = RecordingSession([
        ExecuteResult(scalar_values=["MEOW-1", "MEOW-2"]),
    ])
    repo = PricingRepository(session)

    assert repo.get_all_meow_skus() == ["MEOW-1", "MEOW-2"]
    assert _normalized(session.calls[0][0]) == "SELECT meow_sku FROM meow_sku_map"
    assert session.calls[0][1] == {}


def test_get_all_meow_skus_returns_empty_list_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = PricingRepository(session)

    assert repo.get_all_meow_skus() == []


def test_get_costs_for_skus_sql_contract_filters_currency_and_chooses_lowest_valid_price():
    now = datetime.now(timezone.utc)
    session = RecordingSession([
        FetchResult([
            (
                "MEOW-1",
                "USD",
                Decimal("18.00"),
                now - timedelta(days=1),
                now + timedelta(days=1),
                Decimal("22.00"),
                Decimal("4.50"),
                Decimal("20.00"),
            ),
            (
                "MEOW-2",
                "USD",
                Decimal("15.00"),
                now - timedelta(days=3),
                now - timedelta(days=1),
                Decimal("21.00"),
                None,
                Decimal("19.00"),
            ),
            (
                "MEOW-EUR",
                "EUR",
                Decimal("10.00"),
                now - timedelta(days=1),
                now + timedelta(days=1),
                Decimal("11.00"),
                Decimal("2.00"),
                Decimal("9.00"),
            ),
            (
                "MEOW-NOPRICE",
                "USD",
                None,
                None,
                None,
                None,
                Decimal("1.00"),
                None,
            ),
        ]),
    ])
    repo = PricingRepository(session)

    costs = repo.get_costs_for_skus(["MEOW-1", "MEOW-2", "MEOW-EUR", "MEOW-NOPRICE"])

    sql = _normalized(session.calls[0][0])
    assert costs == {
        "MEOW-1": (Decimal("18.00"), Decimal("4.50")),
        "MEOW-2": (Decimal("19.00"), Decimal("0")),
    }
    assert "SELECT m.meow_sku, pbp.currency, pbp.discounted_price" in sql
    assert "FROM meow_sku_map m" in sql
    assert "JOIN giga_product_base_prices pbp" in sql
    assert "ON m.vendor_sku = pbp.giga_sku" in sql
    assert "AND m.vendor_source = 'giga'" in sql
    assert "WHERE m.meow_sku = ANY(:meow_sku_list)" in sql
    assert session.calls[0][1] == {
        "meow_sku_list": ["MEOW-1", "MEOW-2", "MEOW-EUR", "MEOW-NOPRICE"],
    }


def test_get_costs_for_skus_returns_empty_mapping_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = PricingRepository(session)

    assert repo.get_costs_for_skus(["MEOW-1"]) == {}


def test_upsert_final_prices_empty_input_does_not_open_connection():
    session = RecordingSession(connection=None)
    repo = PricingRepository(session)

    repo.upsert_final_prices([])

    assert session.calls == []


def test_upsert_final_prices_uses_temp_table_copy_and_conflict_update():
    cursor = FakeCursor()
    session = RecordingSession(connection=FakeConnection(cursor))
    repo = PricingRepository(session)

    repo.upsert_final_prices([
        {
            "meow_sku": "MEOW-1",
            "final_price": Decimal("29.99"),
            "currency": "USD",
            "cost_at_pricing": Decimal("12.50"),
            "pricing_formula_version": "v1",
            "pricing_params_snapshot": '{"commission_rate": 0.15}',
        },
        {
            "meow_sku": "MEOW-2",
            "final_price": Decimal("39.99"),
            "currency": "USD",
            "cost_at_pricing": Decimal("17.50"),
            "pricing_formula_version": "v2",
            "pricing_params_snapshot": '{"commission_rate": 0.12}',
        },
    ])

    assert len(cursor.executed_sql) == 2
    assert "CREATE TEMP TABLE tmp_final_prices" in cursor.executed_sql[0]
    assert "ON COMMIT DROP" in cursor.executed_sql[0]
    assert "INSERT INTO product_final_prices" in cursor.executed_sql[1]
    assert "ON CONFLICT (meow_sku) DO UPDATE SET" in cursor.executed_sql[1]
    assert len(cursor.copy_calls) == 1
    copy_sql, csv_payload = cursor.copy_calls[0]
    assert copy_sql == "COPY tmp_final_prices FROM STDIN WITH CSV"
    assert "MEOW-1,29.99,USD,12.50,v1" in csv_payload
    assert "MEOW-2,39.99,USD,17.50,v2" in csv_payload


def test_upsert_final_prices_reraises_copy_errors():
    session = RecordingSession(connection=FakeConnection(FailingCursor()))
    repo = PricingRepository(session)

    with pytest.raises(RuntimeError, match="copy failed"):
        repo.upsert_final_prices([
            {
                "meow_sku": "MEOW-1",
                "final_price": Decimal("29.99"),
                "currency": "USD",
                "cost_at_pricing": Decimal("12.50"),
                "pricing_formula_version": "v1",
                "pricing_params_snapshot": "{}",
            },
        ])
