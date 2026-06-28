"""SQL contract tests for Layer 1 pending rule review repository."""

from src.repositories.pending_rule_review_repository import PendingRuleReviewRepository


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class MappingRows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)


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


def test_upsert_decision_sql_contract():
    session = RecordingSession([ScalarResult(7)])
    repo = PendingRuleReviewRepository(session)

    row_id = repo.upsert_decision(
        category="CHAIR",
        path_key="number_of_items",
        issue_type="unsafe_default",
        decision="safe_default",
        reviewer="operator@test",
        detail="approved fallback default",
        patch_summary={"safe_default_sources": 1},
    )

    assert row_id == 7
    sql, params = session.calls[0]
    assert "INSERT INTO amz_listing_pending_rule_review" in sql
    assert "ON CONFLICT (category, path_key, issue_type) DO UPDATE SET" in sql
    assert params["category"] == "CHAIR"
    assert params["decision"] == "safe_default"


def test_list_decisions_sql_contract():
    session = RecordingSession(
        [
            MappingRows(
                [
                    {
                        "id": 1,
                        "category": "CHAIR",
                        "path_key": "number_of_items",
                        "issue_type": "unsafe_default",
                        "decision": "safe_default",
                        "reviewer": "operator@test",
                        "detail": None,
                        "patch_summary": "{}",
                        "created_at": None,
                        "decided_at": None,
                        "updated_at": None,
                    }
                ]
            )
        ]
    )
    repo = PendingRuleReviewRepository(session)

    rows = repo.list_decisions("CHAIR")

    assert rows[0]["path_key"] == "number_of_items"
    sql, params = session.calls[0]
    assert "FROM amz_listing_pending_rule_review" in sql
    assert params["category"] == "CHAIR"
