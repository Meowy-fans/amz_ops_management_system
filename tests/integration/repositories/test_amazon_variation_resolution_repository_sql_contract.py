"""SQL contract tests for variation resolution audit repository."""

from src.repositories.amazon_variation_resolution_repository import (
    AmazonVariationResolutionRepository,
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


def test_insert_run_sql_contract_stores_variation_resolution_snapshots():
    session = RecordingSession([ScalarResult(21)])
    repo = AmazonVariationResolutionRepository(session)

    run_id = repo.insert_run(
        mode="append_child",
        parent_sku="PARENT-1",
        product_type="CABINET",
        selected_theme="Color",
        decision="blocked",
        child_skus=["MEOW-E"],
        candidate_snapshot={"Color": {"MEOW-E": {"color_name": "White"}}},
        score_snapshot={"Color": {"score": 95}},
        existing_family_snapshot={"parent_sku": "PARENT-1"},
        finding_snapshot=[{"code": "DUPLICATE_VARIATION_ATTRIBUTES"}],
        resolver_version="variation_theme_strategy_v1",
    )

    assert run_id == 21
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "INSERT INTO amazon_variation_resolution_runs" in sql
    assert params["mode"] == "append_child"
    assert params["parent_sku"] == "PARENT-1"
    assert params["selected_theme"] == "Color"
    assert params["decision"] == "blocked"
    assert '"MEOW-E"' in params["child_skus"]
    assert '"score": 95' in params["score_snapshot"]
    assert '"DUPLICATE_VARIATION_ATTRIBUTES"' in params["finding_snapshot"]
