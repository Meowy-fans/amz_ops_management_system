"""SQL contract tests for commercial gate audit repository."""

from src.repositories.amazon_listing_commercial_gate_repository import (
    AmazonListingCommercialGateRepository,
)


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class RecordingSession:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if not self.results:
            raise AssertionError("Unexpected execute call")
        return self.results.pop(0)

    def commit(self):
        pass


def _normalized(sql):
    return " ".join(sql.split())


def test_insert_run_sql_contract_stores_snapshots():
    session = RecordingSession([ScalarResult(11)])
    repo = AmazonListingCommercialGateRepository(session)

    run_id = repo.insert_run(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        gate_version="commercial_gate_v1",
        decision="blocked",
        blocking_codes=["PRICE_STALE"],
        warning_codes=["ZERO_INVENTORY_ALLOWED"],
        input_snapshot={"final_price": 199.99},
        rule_snapshot={"price_max_age_hours": 24},
        finding_snapshot=[{"code": "PRICE_STALE"}],
    )

    assert run_id == 11
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "INSERT INTO amazon_listing_commercial_gate_runs" in sql
    assert params["sku"] == "MEOW1"
    assert params["decision"] == "blocked"
    assert '"PRICE_STALE"' in params["blocking_codes"]
    assert '"final_price": 199.99' in params["input_snapshot"]
