import json

import pytest

from src.repositories.amz_listing_log_repository import AmzListingLogRepository


class MappingRows:
    def __init__(self, rows=None, first_row=None):
        self.rows = rows or []
        self.first_row = first_row

    def mappings(self):
        return self

    def first(self):
        return self.first_row

    def all(self):
        return self.rows


class ExecuteResult:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount


class RecordingSession:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []
        self.rollbacks = 0

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return ExecuteResult()

    def rollback(self):
        self.rollbacks += 1


def _normalized(sql):
    return " ".join(sql.split())


def test_find_log_for_family_empty_input_short_circuits():
    session = RecordingSession()
    repo = AmzListingLogRepository(session)

    assert repo.find_log_for_family([]) is None
    assert session.calls == []


def test_find_log_for_family_sql_contract_returns_latest_mapping():
    session = RecordingSession([
        MappingRows(first_row={
            "parent_sku": "PARENT-1",
            "status": "GENERATED",
            "variation_theme": "Color",
        }),
    ])
    repo = AmzListingLogRepository(session)

    assert repo.find_log_for_family(["MEOW-1", "MEOW-2"]) == {
        "parent_sku": "PARENT-1",
        "status": "GENERATED",
        "variation_theme": "Color",
    }
    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "SELECT parent_sku, status, variation_theme" in normalized
    assert "FROM amz_listing_log" in normalized
    assert "WHERE meow_sku = ANY(:family)" in normalized
    assert "ORDER BY created_at DESC" in normalized
    assert "LIMIT 1" in normalized
    assert params == {"family": ["MEOW-1", "MEOW-2"]}


def test_find_log_for_family_returns_none_when_no_row_and_reraises_database_errors():
    assert AmzListingLogRepository(
        RecordingSession([MappingRows(first_row=None)])
    ).find_log_for_family(["MEOW-1"]) is None

    with pytest.raises(RuntimeError, match="database unavailable"):
        AmzListingLogRepository(
            RecordingSession([RuntimeError("database unavailable")])
        ).find_log_for_family(["MEOW-1"])


def test_get_family_details_by_parent_sql_contract_decodes_json_strings():
    session = RecordingSession([
        MappingRows(rows=[
            {"meow_sku": "MEOW-1", "variation_attributes": '{"Color":"Black"}'},
            {"meow_sku": "MEOW-2", "variation_attributes": {"Color": "White"}},
            {"meow_sku": "MEOW-3", "variation_attributes": "not-json"},
        ]),
    ])
    repo = AmzListingLogRepository(session)

    assert repo.get_family_details_by_parent("PARENT-1") == [
        {"meow_sku": "MEOW-1", "variation_attributes": {"Color": "Black"}},
        {"meow_sku": "MEOW-2", "variation_attributes": {"Color": "White"}},
        {"meow_sku": "MEOW-3", "variation_attributes": {}},
    ]
    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "SELECT meow_sku, variation_attributes" in normalized
    assert "FROM amz_listing_log" in normalized
    assert "WHERE parent_sku = :parent_sku" in normalized
    assert params == {"parent_sku": "PARENT-1"}


def test_get_family_details_by_parent_reraises_database_errors():
    with pytest.raises(RuntimeError, match="database unavailable"):
        AmzListingLogRepository(
            RecordingSession([RuntimeError("database unavailable")])
        ).get_family_details_by_parent("PARENT-1")


def test_bulk_insert_log_empty_input_short_circuits():
    session = RecordingSession()
    repo = AmzListingLogRepository(session)

    repo.bulk_insert_log([])

    assert session.calls == []


def test_bulk_insert_log_sql_contract_serializes_variation_attributes_and_upserts():
    session = RecordingSession()
    repo = AmzListingLogRepository(session)
    logs = [
        {
            "meow_sku": "MEOW-1",
            "parent_sku": "PARENT-1",
            "variation_attributes": {"Color": "Black"},
            "listing_batch_id": "batch-1",
            "status": "GENERATED",
            "variation_theme": "Color",
        }
    ]

    repo.bulk_insert_log(logs)

    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "INSERT INTO amz_listing_log" in normalized
    assert "ON CONFLICT (meow_sku) DO UPDATE SET" in normalized
    assert "created_at = CURRENT_TIMESTAMP" in normalized
    assert params == logs
    assert json.loads(params[0]["variation_attributes"]) == {"Color": "Black"}


def test_bulk_insert_log_reraises_database_errors():
    session = RecordingSession([RuntimeError("insert failed")])
    repo = AmzListingLogRepository(session)

    with pytest.raises(RuntimeError, match="insert failed"):
        repo.bulk_insert_log([
            {
                "meow_sku": "MEOW-1",
                "parent_sku": None,
                "variation_attributes": {},
                "listing_batch_id": "batch-1",
                "status": "GENERATED",
                "variation_theme": None,
            }
        ])


def test_bulk_update_status_to_listed_sql_contract_returns_rowcount():
    session = RecordingSession([ExecuteResult(rowcount=3)])
    repo = AmzListingLogRepository(session)

    assert repo.bulk_update_status_to_listed() == 3
    sql = _normalized(session.calls[0][0])
    assert "UPDATE amz_listing_log" in sql
    assert "SET status = 'LISTED'" in sql
    assert "WHERE status = 'GENERATED'" in sql
    assert "FROM amz_all_listing_report" in sql
    assert "WHERE status IN ('Active', 'Inactive')" in sql
    assert session.rollbacks == 0


def test_bulk_update_status_to_listed_rolls_back_and_returns_negative_one_on_error():
    session = RecordingSession([RuntimeError("update failed")])
    repo = AmzListingLogRepository(session)

    assert repo.bulk_update_status_to_listed() == -1
    assert session.rollbacks == 1
