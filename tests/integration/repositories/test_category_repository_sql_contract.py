import pytest

from src.repositories.category_repository import CategoryRepository


class FetchResult:
    def __init__(self, rows=None, rowcount=0):
        self.rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self.rows


class RecordingSession:
    def __init__(self, results=None, rollback_error=None):
        self.results = list(results or [])
        self.rollback_error = rollback_error
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query, params=None):
        self.calls.append((str(query), params))
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
        if self.rollback_error:
            raise self.rollback_error


def _normalized(sql):
    return " ".join(sql.split())


def test_get_sku_to_category_mapping_sql_contract():
    rows = [("M001", "CABINET"), ("M002", None)]
    session = RecordingSession([FetchResult(rows=rows)])
    repository = CategoryRepository(session)

    mapping = repository.get_sku_to_category_mapping(["M001", "M002"])

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert mapping == rows
    assert "FROM meow_sku_map m JOIN giga_product_sync_records psr" in normalized_sql
    assert "LEFT JOIN supplier_categories_map scm" in normalized_sql
    assert "LOWER(psr.category_code) = LOWER(scm.supplier_category_code)" in (
        normalized_sql
    )
    assert "WHERE m.meow_sku = ANY (:meow_sku_list)" in normalized_sql
    assert params == {"meow_sku_list": ["M001", "M002"]}


def test_get_sku_to_category_mapping_rolls_back_and_returns_empty_on_error():
    session = RecordingSession(
        [RuntimeError("select failed")],
        rollback_error=RuntimeError("rollback failed"),
    )
    repository = CategoryRepository(session)

    assert repository.get_sku_to_category_mapping(["M001"]) == []
    assert session.rollbacks == 1


def test_get_existing_category_codes_sql_contract_returns_set():
    session = RecordingSession([FetchResult(rows=[("CAB001",), ("MIR001",)])])
    repository = CategoryRepository(session)

    codes = repository.get_existing_category_codes(platform="giga")

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert codes == {"CAB001", "MIR001"}
    assert "FROM supplier_categories_map" in normalized_sql
    assert "WHERE supplier_platform = :platform" in normalized_sql
    assert params == {"platform": "giga"}


def test_get_existing_category_codes_returns_empty_set_on_error():
    session = RecordingSession([RuntimeError("select failed")])
    repository = CategoryRepository(session)

    assert repository.get_existing_category_codes() == set()


def test_get_giga_category_codes_sql_contract_defaults_name_to_code():
    session = RecordingSession([FetchResult(rows=[("CAB001", "Cabinet"), ("MIR001", None)])])
    repository = CategoryRepository(session)

    categories = repository.get_giga_category_codes()

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert categories == [
        {"category_code": "CAB001", "category_name": "Cabinet"},
        {"category_code": "MIR001", "category_name": "MIR001"},
    ]
    assert "SELECT DISTINCT category_code, raw_data->>'category' as category_name" in (
        normalized_sql
    )
    assert "FROM giga_product_sync_records" in normalized_sql
    assert "WHERE category_code IS NOT NULL AND category_code != ''" in normalized_sql
    assert "ORDER BY category_code" in normalized_sql
    assert params is None


def test_get_giga_category_codes_returns_empty_list_on_error():
    session = RecordingSession([RuntimeError("select failed")])
    repository = CategoryRepository(session)

    assert repository.get_giga_category_codes() == []


def test_batch_insert_category_mappings_short_circuits_empty_input():
    session = RecordingSession()
    repository = CategoryRepository(session)

    assert repository.batch_insert_category_mappings([]) == 0
    assert session.calls == []
    assert session.commits == 0


def test_batch_insert_category_mappings_sql_contract_commits_and_returns_rowcount():
    mappings = [
        {
            "supplier_platform": "giga",
            "supplier_category_code": "CAB001",
            "supplier_category_name": "Cabinet",
            "standard_category_name": "",
        }
    ]
    session = RecordingSession([FetchResult(rowcount=1)])
    repository = CategoryRepository(session)

    inserted_count = repository.batch_insert_category_mappings(mappings)

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert inserted_count == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert "INSERT INTO supplier_categories_map" in normalized_sql
    assert "ON CONFLICT (supplier_platform, supplier_category_code) DO NOTHING" in (
        normalized_sql
    )
    assert params == mappings


def test_batch_insert_category_mappings_rolls_back_and_reraises_on_error():
    session = RecordingSession([RuntimeError("insert failed")])
    repository = CategoryRepository(session)

    with pytest.raises(RuntimeError, match="insert failed"):
        repository.batch_insert_category_mappings(
            [
                {
                    "supplier_platform": "giga",
                    "supplier_category_code": "CAB001",
                    "supplier_category_name": "Cabinet",
                    "standard_category_name": "",
                }
            ]
        )
    assert session.rollbacks == 1


def test_get_unmapped_categories_with_product_count_sql_contract():
    session = RecordingSession([FetchResult(rows=[("CAB001", "Cabinet", 5), ("MIR001", None, 2)])])
    repository = CategoryRepository(session)

    unmapped = repository.get_unmapped_categories_with_product_count(platform="giga")

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert unmapped == [
        {"category_code": "CAB001", "category_name": "Cabinet", "product_count": 5},
        {"category_code": "MIR001", "category_name": "MIR001", "product_count": 2},
    ]
    assert "FROM supplier_categories_map scm LEFT JOIN giga_product_sync_records psr" in (
        normalized_sql
    )
    assert "AND (scm.standard_category_name = '' OR scm.standard_category_name IS NULL)" in (
        normalized_sql
    )
    assert "ORDER BY product_count DESC" in normalized_sql
    assert params == {"platform": "giga"}


def test_get_unmapped_categories_with_product_count_returns_empty_list_on_error():
    session = RecordingSession([RuntimeError("select failed")])
    repository = CategoryRepository(session)

    assert repository.get_unmapped_categories_with_product_count() == []


def test_get_valid_amazon_categories_sql_contract_returns_lowercase_set():
    session = RecordingSession([FetchResult(rows=[("cabinet",), ("home_mirror",)])])
    repository = CategoryRepository(session)

    categories = repository.get_valid_amazon_categories()

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert categories == {"cabinet", "home_mirror"}
    assert "SELECT DISTINCT LOWER(category) as category" in normalized_sql
    assert "FROM amazon_cat_templates" in normalized_sql
    assert "WHERE category IS NOT NULL AND category != ''" in normalized_sql
    assert params is None


def test_get_valid_amazon_categories_returns_empty_set_on_error():
    session = RecordingSession([RuntimeError("select failed")])
    repository = CategoryRepository(session)

    assert repository.get_valid_amazon_categories() == set()


def test_batch_update_category_mappings_short_circuits_empty_input():
    session = RecordingSession()
    repository = CategoryRepository(session)

    assert repository.batch_update_category_mappings([]) == 0
    assert session.calls == []
    assert session.commits == 0


def test_batch_update_category_mappings_sql_contract_sums_rowcounts_and_commits():
    updates = [
        {
            "supplier_platform": "giga",
            "supplier_category_code": "CAB001",
            "standard_category_name": "CABINET",
        },
        {
            "supplier_platform": "giga",
            "supplier_category_code": "MIR001",
            "standard_category_name": "HOME_MIRROR",
        },
    ]
    session = RecordingSession([FetchResult(rowcount=1), FetchResult(rowcount=2)])
    repository = CategoryRepository(session)

    updated_count = repository.batch_update_category_mappings(updates)

    first_sql, first_params = session.calls[0]
    second_sql, second_params = session.calls[1]
    normalized_sql = _normalized(first_sql)
    assert updated_count == 3
    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(session.calls) == 2
    assert "UPDATE supplier_categories_map SET standard_category_name = :standard_category_name" in (
        normalized_sql
    )
    assert "WHERE supplier_platform = :supplier_platform" in normalized_sql
    assert "AND supplier_category_code = :supplier_category_code" in normalized_sql
    assert first_params == updates[0]
    assert _normalized(second_sql) == normalized_sql
    assert second_params == updates[1]


def test_batch_update_category_mappings_rolls_back_and_reraises_on_error():
    session = RecordingSession([FetchResult(rowcount=1), RuntimeError("update failed")])
    repository = CategoryRepository(session)

    with pytest.raises(RuntimeError, match="update failed"):
        repository.batch_update_category_mappings(
            [
                {
                    "supplier_platform": "giga",
                    "supplier_category_code": "CAB001",
                    "standard_category_name": "CABINET",
                },
                {
                    "supplier_platform": "giga",
                    "supplier_category_code": "MIR001",
                    "standard_category_name": "HOME_MIRROR",
                },
            ]
        )
    assert session.rollbacks == 1
