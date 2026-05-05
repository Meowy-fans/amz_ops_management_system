from src.repositories.amz_listing_data_repository import ListingDataRepository


class MappingResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class RowResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
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


def _normalized(sql):
    return " ".join(sql.split())


def test_get_skus_for_update_sql_contract_filters_incomplete_and_missing_vendor_sku():
    session = RecordingSession([
        MappingResult([
            {"amazon_sku": "AMZ-1", "giga_sku": "GIGA-1"},
            {"amazon_sku": "AMZ-2", "giga_sku": "GIGA-2"},
        ]),
    ])
    repo = ListingDataRepository(session)

    result = repo.get_skus_for_update()

    sql = _normalized(session.calls[0][0])
    assert result == [
        {"amazon_sku": "AMZ-1", "giga_sku": "GIGA-1"},
        {"amazon_sku": "AMZ-2", "giga_sku": "GIGA-2"},
    ]
    assert 'SELECT alr."seller-sku" AS amazon_sku, msm.vendor_sku AS giga_sku' in sql
    assert "FROM amz_all_listing_report alr" in sql
    assert 'JOIN meow_sku_map msm ON alr."seller-sku" = msm.meow_sku' in sql
    assert "alr.status <> 'Incomplete'" in sql
    assert "msm.vendor_sku IS NOT NULL" in sql
    assert session.calls[0][1] == {}


def test_get_skus_for_update_returns_empty_list_when_database_fails():
    session = RecordingSession([RuntimeError("database unavailable")])
    repo = ListingDataRepository(session)

    assert repo.get_skus_for_update() == []


def test_get_latest_data_sql_contract_fetches_prices_by_amazon_sku_and_inventory_by_giga_sku():
    session = RecordingSession([
        RowResult([
            ("AMZ-1", "19.99"),
            ("AMZ-2", "31.50"),
        ]),
        RowResult([
            ("GIGA-1", 8),
            ("GIGA-2", 0),
        ]),
    ])
    repo = ListingDataRepository(session)

    price_map, quantity_map = repo.get_latest_data(
        ["AMZ-1", "AMZ-2"],
        ["GIGA-1", "GIGA-2"],
    )

    price_sql = _normalized(session.calls[0][0])
    quantity_sql = _normalized(session.calls[1][0])
    assert price_map == {"AMZ-1": "19.99", "AMZ-2": "31.50"}
    assert quantity_map == {"GIGA-1": 8, "GIGA-2": 0}
    assert "SELECT meow_sku, final_price FROM product_final_prices" in price_sql
    assert "WHERE meow_sku = ANY(:skus)" in price_sql
    assert session.calls[0][1] == {"skus": ["AMZ-1", "AMZ-2"]}
    assert "SELECT giga_sku, quantity FROM giga_inventory" in quantity_sql
    assert "WHERE giga_sku = ANY(:skus)" in quantity_sql
    assert session.calls[1][1] == {"skus": ["GIGA-1", "GIGA-2"]}


def test_get_latest_data_empty_inputs_do_not_hit_database():
    session = RecordingSession([])
    repo = ListingDataRepository(session)

    assert repo.get_latest_data([], []) == ({}, {})
    assert session.calls == []


def test_get_latest_data_keeps_successful_side_when_one_query_fails():
    session = RecordingSession([
        RuntimeError("price unavailable"),
        RowResult([
            ("GIGA-1", 8),
        ]),
    ])
    repo = ListingDataRepository(session)

    price_map, quantity_map = repo.get_latest_data(["AMZ-1"], ["GIGA-1"])

    assert price_map == {}
    assert quantity_map == {"GIGA-1": 8}
    assert len(session.calls) == 2


def test_get_latest_data_keeps_price_data_when_inventory_query_fails():
    session = RecordingSession([
        RowResult([
            ("AMZ-1", "19.99"),
        ]),
        RuntimeError("inventory unavailable"),
    ])
    repo = ListingDataRepository(session)

    price_map, quantity_map = repo.get_latest_data(["AMZ-1"], ["GIGA-1"])

    assert price_map == {"AMZ-1": "19.99"}
    assert quantity_map == {}
    assert len(session.calls) == 2
