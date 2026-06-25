"""SQL contract tests for pending listing review repository."""

from src.repositories.amazon_listing_pending_review_repository import (
    AmazonListingPendingReviewRepository,
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


def test_upsert_pending_sql_contract_stores_review_payloads():
    session = RecordingSession([ScalarResult(7)])
    repo = AmazonListingPendingReviewRepository(session)

    review_id = repo.upsert_pending(
        category="CHAIR",
        sku="SKU1",
        parent_sku=None,
        plan_snapshot={"sku": "SKU1"},
        pending_items=[{"attribute": "included_components"}],
    )

    assert review_id == 7
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "INSERT INTO amz_listing_pending_review" in sql
    assert "ON CONFLICT (category, sku) DO UPDATE" in sql
    assert params["category"] == "CHAIR"
    assert params["sku"] == "SKU1"
    assert '"included_components"' in params["pending_items"]


class MappingRows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return iter(self._rows)


def test_list_reviews_filters_by_category_status_and_decodes_json():
    row = {
        "id": 3,
        "category": "CHAIR",
        "sku": "SKU1",
        "parent_sku": None,
        "plan_snapshot": '{"sku": "SKU1"}',
        "pending_items": '[{"attribute": "included_components"}]',
        "review_decisions": "",
        "review_status": "pending",
        "created_at": None,
        "updated_at": None,
    }
    session = RecordingSession([MappingRows([row])])
    repo = AmazonListingPendingReviewRepository(session)

    rows = repo.list_reviews(category="CHAIR", status="pending", limit=10)

    assert len(rows) == 1
    assert rows[0]["plan_snapshot"] == {"sku": "SKU1"}
    assert rows[0]["pending_items"] == [{"attribute": "included_components"}]
    assert rows[0]["review_decisions"] == []
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "category = :category" in sql
    assert "review_status = :status" in sql
    assert "ORDER BY created_at ASC" in sql
    assert params == {"limit": 10, "category": "CHAIR", "status": "pending"}


def test_save_decisions_sql_contract_updates_status_and_payload():
    session = RecordingSession([ScalarResult(None)])
    repo = AmazonListingPendingReviewRepository(session)

    repo.save_decisions(
        review_id=5,
        decisions=[{"attribute": "included_components", "decision": "approved"}],
        status="completed",
    )

    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "UPDATE amz_listing_pending_review" in sql
    assert "review_decisions = :review_decisions" in sql
    assert "review_status = :review_status" in sql
    assert params["review_id"] == 5
    assert params["review_status"] == "completed"
    assert '"approved"' in params["review_decisions"]


def test_get_attribute_accuracy_sql_contract_uses_completed_decisions():
    class MappingResult:
        def mappings(self):
            return self

        def first(self):
            return {"accuracy": 0.75}

    session = RecordingSession([MappingResult()])
    repo = AmazonListingPendingReviewRepository(session)

    accuracy = repo.get_attribute_accuracy("CHAIR", "included_components", 10)

    assert accuracy == 0.75
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "jsonb_array_elements(review_decisions)" in sql
    assert "review_status = 'completed'" in sql
    assert params == {
        "product_type": "CHAIR",
        "attribute": "included_components",
        "min_samples": 10,
    }
