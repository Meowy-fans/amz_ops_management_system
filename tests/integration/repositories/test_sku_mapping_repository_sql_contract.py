import pytest

from src.repositories.sku_mapping_repository import SkuMappingRepository


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FetchResult:
    def __init__(self, scalar_value=None, scalar_values=None, one_row=None):
        self.scalar_value = scalar_value
        self.scalar_values = scalar_values or []
        self.one_row = one_row

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalars(self):
        return ScalarResult(self.scalar_values)

    def fetchone(self):
        return self.one_row


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


def test_find_by_vendor_sku_sql_contract_returns_meow_sku():
    session = RecordingSession([FetchResult(scalar_value="MEOW-1")])
    repo = SkuMappingRepository(session)

    assert repo.find_by_vendor_sku("giga", "GIGA-1") == "MEOW-1"
    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "SELECT meow_sku" in normalized
    assert "FROM meow_sku_map" in normalized
    assert "WHERE vendor_source = :vendor_source" in normalized
    assert "AND vendor_sku = :vendor_sku" in normalized
    assert "LIMIT 1" in normalized
    assert params == {"vendor_source": "giga", "vendor_sku": "GIGA-1"}


def test_find_by_vendor_sku_returns_none_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = SkuMappingRepository(session)

    assert repo.find_by_vendor_sku("giga", "GIGA-1") is None


def test_get_skus_from_llm_details_sql_contract_returns_distinct_non_null_skus():
    session = RecordingSession([
        FetchResult(scalar_values=["GIGA-1", "GIGA-2"]),
    ])
    repo = SkuMappingRepository(session)

    assert repo.get_skus_from_llm_details() == ["GIGA-1", "GIGA-2"]
    sql = _normalized(session.calls[0][0])
    assert "SELECT DISTINCT sku_id" in sql
    assert "FROM ds_api_product_details" in sql
    assert "WHERE sku_id IS NOT NULL" in sql


def test_get_skus_from_llm_details_returns_empty_list_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = SkuMappingRepository(session)

    assert repo.get_skus_from_llm_details() == []


def test_filter_unmapped_skus_sql_contract_uses_unnest_and_left_join():
    session = RecordingSession([
        FetchResult(scalar_values=["GIGA-2", "GIGA-3"]),
    ])
    repo = SkuMappingRepository(session)

    assert repo.filter_unmapped_skus(["GIGA-1", "GIGA-2", "GIGA-3"], "giga") == [
        "GIGA-2",
        "GIGA-3",
    ]
    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "FROM (SELECT unnest(:vendor_sku_list) AS sku) AS v" in normalized
    assert "LEFT JOIN meow_sku_map m" in normalized
    assert "ON v.sku = m.vendor_sku" in normalized
    assert "AND m.vendor_source = :vendor_source" in normalized
    assert "WHERE m.vendor_sku IS NULL" in normalized
    assert params == {
        "vendor_sku_list": ["GIGA-1", "GIGA-2", "GIGA-3"],
        "vendor_source": "giga",
    }


def test_filter_unmapped_skus_returns_empty_list_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = SkuMappingRepository(session)

    assert repo.filter_unmapped_skus(["GIGA-1"], "giga") == []


def test_bulk_insert_mappings_sql_contract_passes_mappings_as_executemany_params():
    session = RecordingSession()
    repo = SkuMappingRepository(session)
    mappings = [
        {"meow_sku": "MEOW-1", "vendor_source": "giga", "vendor_sku": "GIGA-1"},
        {"meow_sku": "MEOW-2", "vendor_source": "giga", "vendor_sku": "GIGA-2"},
    ]

    repo.bulk_insert_mappings(mappings)

    sql, params = session.calls[0]
    normalized = _normalized(sql)
    assert "INSERT INTO meow_sku_map (meow_sku, vendor_source, vendor_sku)" in normalized
    assert "VALUES (:meow_sku, :vendor_source, :vendor_sku)" in normalized
    assert params == mappings


def test_bulk_insert_mappings_reraises_database_errors():
    session = RecordingSession([RuntimeError("insert failed")])
    repo = SkuMappingRepository(session)

    with pytest.raises(RuntimeError, match="insert failed"):
        repo.bulk_insert_mappings([
            {"meow_sku": "MEOW-1", "vendor_source": "giga", "vendor_sku": "GIGA-1"},
        ])


def test_get_statistics_sql_contract_counts_mapping_totals():
    session = RecordingSession([
        FetchResult(one_row=(10, 2, 9)),
    ])
    repo = SkuMappingRepository(session)

    assert repo.get_statistics() == {
        "total": 10,
        "sources": 2,
        "unique_vendor_skus": 9,
    }
    sql = _normalized(session.calls[0][0])
    assert "COUNT(*) as total" in sql
    assert "COUNT(DISTINCT vendor_source) as sources" in sql
    assert "COUNT(DISTINCT vendor_sku) as unique_vendor_skus" in sql
    assert "FROM meow_sku_map" in sql


def test_get_statistics_returns_zero_counts_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = SkuMappingRepository(session)

    assert repo.get_statistics() == {
        "total": 0,
        "sources": 0,
        "unique_vendor_skus": 0,
    }
