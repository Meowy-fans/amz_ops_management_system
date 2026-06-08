import json

from src.repositories.llm_product_detail_repository import LLMProductDetailRepository


class FetchResult:
    def __init__(self, rows=None, one_row=None):
        self.rows = rows or []
        self.one_row = one_row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one_row


class RecordingSession:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return FetchResult()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _normalized(sql):
    return " ".join(sql.split())


def _detail_tuple(sku="GIGA-1"):
    return (
        sku,
        "Product name",
        "Point 1",
        "Point 2",
        "Point 3",
        "Point 4",
        "Point 5",
        "Description",
        "qwen",
        '{"sku":"GIGA-1"}',
    )


def test_get_unprocessed_skus_sql_contract_excludes_existing_details():
    session = RecordingSession([
        FetchResult(rows=[("GIGA-1",), ("GIGA-2",)]),
    ])
    repo = LLMProductDetailRepository(session)

    assert repo.get_unprocessed_skus() == ["GIGA-1", "GIGA-2"]
    sql = _normalized(session.calls[0][0])
    assert "SELECT DISTINCT giga_sku" in sql
    assert "FROM giga_product_sync_records" in sql
    assert "WHERE raw_data IS NOT NULL" in sql
    assert "NOT EXISTS" in sql
    assert "FROM ds_api_product_details" in sql
    assert "WHERE sku_id = giga_sku" in sql
    assert "ORDER BY giga_sku ASC" in sql


def test_get_unprocessed_skus_returns_empty_list_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = LLMProductDetailRepository(session)

    assert repo.get_unprocessed_skus() == []


def test_get_product_raw_data_sql_contract_returns_dict_payload():
    raw_data = {"sku": "GIGA-1", "name": "Product 1"}
    session = RecordingSession([
        FetchResult(one_row=(raw_data,)),
    ])
    repo = LLMProductDetailRepository(session)

    assert repo.get_product_raw_data("GIGA-1") == raw_data
    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "SELECT raw_data" in normalized
    assert "FROM giga_product_sync_records" in normalized
    assert "WHERE giga_sku = :sku" in normalized
    assert "LIMIT 1" in normalized
    assert params == {"sku": "GIGA-1"}


def test_get_product_raw_data_decodes_json_string_payload():
    raw_data = {"sku": "GIGA-1", "name": "Product 1"}
    session = RecordingSession([
        FetchResult(one_row=(json.dumps(raw_data),)),
    ])
    repo = LLMProductDetailRepository(session)

    assert repo.get_product_raw_data("GIGA-1") == raw_data


def test_get_product_raw_data_returns_none_for_missing_empty_invalid_or_failed_rows():
    assert LLMProductDetailRepository(
        RecordingSession([FetchResult(one_row=None)])
    ).get_product_raw_data("GIGA-1") is None
    assert LLMProductDetailRepository(
        RecordingSession([FetchResult(one_row=(None,))])
    ).get_product_raw_data("GIGA-1") is None
    assert LLMProductDetailRepository(
        RecordingSession([FetchResult(one_row=("not-json",))])
    ).get_product_raw_data("GIGA-1") is None
    assert LLMProductDetailRepository(
        RecordingSession([RuntimeError("database unavailable")])
    ).get_product_raw_data("GIGA-1") is None


def test_get_product_type_for_sku_resolves_standard_category():
    session = RecordingSession([
        FetchResult(one_row=("cabinet",)),
    ])
    repo = LLMProductDetailRepository(session)

    assert repo.get_product_type_for_sku("GIGA-1") == "CABINET"
    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "SELECT scm.standard_category_name" in normalized
    assert "FROM giga_product_sync_records psr" in normalized
    assert "LEFT JOIN supplier_categories_map scm" in normalized
    assert "LOWER(psr.category_code) = LOWER(scm.supplier_category_code)" in normalized
    assert "scm.supplier_platform = 'giga'" in normalized
    assert "WHERE psr.giga_sku = :sku" in normalized
    assert params == {"sku": "GIGA-1"}


def test_get_product_type_for_sku_returns_none_when_missing_or_database_fails():
    assert LLMProductDetailRepository(
        RecordingSession([FetchResult(one_row=None)])
    ).get_product_type_for_sku("GIGA-1") is None
    assert LLMProductDetailRepository(
        RecordingSession([RuntimeError("database unavailable")])
    ).get_product_type_for_sku("GIGA-1") is None


def test_batch_save_details_empty_input_short_circuits():
    session = RecordingSession()
    repo = LLMProductDetailRepository(session)

    assert repo.batch_save_details([]) == 0
    assert session.calls == []
    assert session.commits == 0


def test_batch_save_details_filters_empty_rows_and_commits_executemany_insert():
    session = RecordingSession()
    repo = LLMProductDetailRepository(session)

    assert repo.batch_save_details([_detail_tuple("GIGA-1"), None, _detail_tuple("GIGA-2")]) == 2

    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "INSERT INTO ds_api_product_details" in normalized
    assert "CAST(:raw_json AS jsonb)" in normalized
    assert params == [
        {
            "sku_id": "GIGA-1",
            "product_name": "Product name",
            "sp1": "Point 1",
            "sp2": "Point 2",
            "sp3": "Point 3",
            "sp4": "Point 4",
            "sp5": "Point 5",
            "product_desc": "Description",
            "calling_agent": "qwen",
            "raw_json": '{"sku":"GIGA-1"}',
        },
        {
            "sku_id": "GIGA-2",
            "product_name": "Product name",
            "sp1": "Point 1",
            "sp2": "Point 2",
            "sp3": "Point 3",
            "sp4": "Point 4",
            "sp5": "Point 5",
            "product_desc": "Description",
            "calling_agent": "qwen",
            "raw_json": '{"sku":"GIGA-1"}',
        },
    ]
    assert session.commits == 1
    assert session.rollbacks == 0


def test_batch_save_details_rolls_back_and_returns_zero_when_database_fails():
    session = RecordingSession([RuntimeError("insert failed")])
    repo = LLMProductDetailRepository(session)

    assert repo.batch_save_details([_detail_tuple()]) == 0
    assert session.commits == 0
    assert session.rollbacks == 1


def test_get_statistics_sql_contract_counts_total_and_unique_skus():
    session = RecordingSession([
        FetchResult(one_row=(12, 9)),
    ])
    repo = LLMProductDetailRepository(session)

    assert repo.get_statistics() == {"total": 12, "unique_skus": 9}
    sql = _normalized(session.calls[0][0])
    assert "COUNT(*) as total" in sql
    assert "COUNT(DISTINCT sku_id) as unique_skus" in sql
    assert "FROM ds_api_product_details" in sql


def test_get_statistics_returns_zero_counts_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = LLMProductDetailRepository(session)

    assert repo.get_statistics() == {"total": 0, "unique_skus": 0}
