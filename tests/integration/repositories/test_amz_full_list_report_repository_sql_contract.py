import pandas as pd
import pytest

from src.repositories.amz_full_list_report_repository import (
    AmzFullListReportRepository,
)


class FetchResult:
    def __init__(self, one_row=None):
        self.one_row = one_row

    def fetchone(self):
        return self.one_row


class RecordingSession:
    def __init__(self, results=None, bind="db-bind"):
        self.results = list(results or [])
        self.bind = bind
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((str(query), params))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return FetchResult()


def _normalized(sql):
    return " ".join(sql.split())


def test_upsert_from_dataframe_short_circuits_empty_dataframe(monkeypatch):
    session = RecordingSession()
    repository = AmzFullListReportRepository(session)

    def fail_to_sql(*args, **kwargs):
        raise AssertionError("empty dataframe should not be written to SQL")

    monkeypatch.setattr(pd.DataFrame, "to_sql", fail_to_sql)

    repository.upsert_from_dataframe(pd.DataFrame())

    assert session.calls == []


def test_upsert_from_dataframe_sql_contract_writes_temp_table_upserts_and_drops(
    monkeypatch,
):
    session = RecordingSession()
    repository = AmzFullListReportRepository(session)
    df = pd.DataFrame(
        [
            {
                "listing-id": "L1",
                "seller-sku": "SKU-1",
                "asin1": "ASIN1",
                "item-name": "Item 1",
                "price": 12.5,
                "quantity": 3,
                "status": "Active",
            }
        ]
    )
    to_sql_calls = []

    def record_to_sql(self, name, con, if_exists, index, method):
        to_sql_calls.append(
            {
                "rows": len(self),
                "name": name,
                "con": con,
                "if_exists": if_exists,
                "index": index,
                "method": method,
            }
        )

    monkeypatch.setattr(pd.DataFrame, "to_sql", record_to_sql)

    repository.upsert_from_dataframe(df)

    upsert_sql = _normalized(session.calls[0][0])
    drop_sql = _normalized(session.calls[1][0])
    temp_table = to_sql_calls[0]["name"]
    assert len(to_sql_calls) == 1
    assert to_sql_calls[0] == {
        "rows": 1,
        "name": temp_table,
        "con": "db-bind",
        "if_exists": "replace",
        "index": False,
        "method": "multi",
    }
    assert temp_table.startswith("temp_amz_")
    assert f"INSERT INTO amz_all_listing_report SELECT * FROM {temp_table}" in (
        upsert_sql
    )
    assert 'ON CONFLICT ("listing-id") DO UPDATE SET' in upsert_sql
    assert '"seller-sku" = EXCLUDED."seller-sku"' in upsert_sql
    assert "last_updated = CURRENT_TIMESTAMP" in upsert_sql
    assert drop_sql == f"DROP TABLE {temp_table}"


def test_upsert_from_dataframe_drops_temp_table_and_reraises_when_upsert_fails(
    monkeypatch,
):
    session = RecordingSession([RuntimeError("upsert failed")])
    repository = AmzFullListReportRepository(session)
    df = pd.DataFrame([{"listing-id": "L1"}])

    def record_to_sql(self, name, con, if_exists, index, method):
        return None

    monkeypatch.setattr(pd.DataFrame, "to_sql", record_to_sql)

    with pytest.raises(RuntimeError, match="upsert failed"):
        repository.upsert_from_dataframe(df)

    assert len(session.calls) == 2
    assert "INSERT INTO amz_all_listing_report" in _normalized(session.calls[0][0])
    assert _normalized(session.calls[1][0]).startswith("DROP TABLE IF EXISTS temp_amz_")


def test_upsert_from_dataframe_suppresses_cleanup_failure_and_reraises_original(
    monkeypatch,
):
    session = RecordingSession(
        [RuntimeError("upsert failed"), RuntimeError("cleanup failed")]
    )
    repository = AmzFullListReportRepository(session)
    df = pd.DataFrame([{"listing-id": "L1"}])

    def record_to_sql(self, name, con, if_exists, index, method):
        return None

    monkeypatch.setattr(pd.DataFrame, "to_sql", record_to_sql)

    with pytest.raises(RuntimeError, match="upsert failed"):
        repository.upsert_from_dataframe(df)

    assert len(session.calls) == 2
    assert _normalized(session.calls[1][0]).startswith("DROP TABLE IF EXISTS temp_amz_")


def test_upsert_from_dataframe_cleans_up_when_to_sql_fails(monkeypatch):
    session = RecordingSession()
    repository = AmzFullListReportRepository(session)
    df = pd.DataFrame([{"listing-id": "L1"}])

    def fail_to_sql(self, name, con, if_exists, index, method):
        raise RuntimeError("to_sql failed")

    monkeypatch.setattr(pd.DataFrame, "to_sql", fail_to_sql)

    with pytest.raises(RuntimeError, match="to_sql failed"):
        repository.upsert_from_dataframe(df)

    assert len(session.calls) == 1
    assert _normalized(session.calls[0][0]).startswith("DROP TABLE IF EXISTS temp_amz_")


def test_get_statistics_sql_contract_defaults_null_counts_to_zero():
    session = RecordingSession([FetchResult(one_row=(None, 2, None))])
    repository = AmzFullListReportRepository(session)

    statistics = repository.get_statistics()

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert statistics == {"total": 0, "active": 2, "unique_asins": 0}
    assert "COUNT(*) as total" in normalized_sql
    assert "COUNT(*) FILTER (WHERE status = 'Active') as active" in normalized_sql
    assert "COUNT(DISTINCT asin1) as unique_asins" in normalized_sql
    assert "FROM amz_all_listing_report" in normalized_sql
    assert params is None
