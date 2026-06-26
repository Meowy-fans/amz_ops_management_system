"""SQL contract tests for V2 path-level pending review repository."""

from src.repositories.amazon_listing_pending_review_v2_repository import (
    AmazonListingPendingReviewV2Repository,
)


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

    def first(self):
        return self._rows[0] if self._rows else None


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


def test_upsert_pending_paths_sql_contract_inserts_path_level_rows():
    session = RecordingSession([ScalarResult(11), ScalarResult(12)])
    repo = AmazonListingPendingReviewV2Repository(session)

    ids = repo.upsert_pending_paths(
        items=[
            {
                "category": "CHAIR",
                "sku": "SKU1",
                "parent_sku": None,
                "path_key": "frame.color",
                "path_key_version": "v2_path_keys_2026_06",
                "attribute": "frame",
                "display_label": "Frame Color",
                "value": "walnut",
                "evidence": "matte walnut frame",
                "confidence_label": "medium",
                "confidence_score": 45,
                "route": "ai_agent",
                "plan_snapshot": {"sku": "SKU1"},
            },
            {
                "category": "CHAIR",
                "sku": "SKU1",
                "parent_sku": None,
                "path_key": "seat.material_type",
                "path_key_version": "v2_path_keys_2026_06",
                "attribute": "seat",
                "display_label": "Seat Material",
                "value": "linen",
                "evidence": "linen cushion",
                "confidence_label": "medium",
                "confidence_score": 40,
                "route": "ai_agent",
                "plan_snapshot": {"sku": "SKU1"},
            },
        ],
    )

    assert ids == [11, 12]
    sql = _normalized(session.calls[0][0])
    assert "INSERT INTO amz_listing_pending_review_v2" in sql
    assert "ON CONFLICT (category, sku, path_key, path_key_version) DO UPDATE" in sql
    assert "review_status = 'pending'" in sql


def test_list_pending_filters_by_category_status_and_route():
    row = {
        "id": 7,
        "category": "CHAIR",
        "sku": "SKU1",
        "parent_sku": None,
        "path_key": "frame.color",
        "path_key_version": "v2_path_keys_2026_06",
        "attribute": "frame",
        "display_label": "Frame Color",
        "value": '"walnut"',
        "evidence": "matte walnut frame",
        "confidence_label": "medium",
        "confidence_score": 45,
        "route": "ai_agent",
        "review_status": "pending",
        "reviewer": None,
        "verdict": None,
        "decided_at": None,
        "created_at": None,
        "updated_at": None,
    }
    session = RecordingSession([MappingRows([row])])
    repo = AmazonListingPendingReviewV2Repository(session)

    rows = repo.list_pending(category="CHAIR", status="pending", route="ai_agent", limit=10)

    assert len(rows) == 1
    assert rows[0]["path_key"] == "frame.color"
    assert rows[0]["value"] == "walnut"
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "category = :category" in sql
    assert "review_status = :status" in sql
    assert "route = :route" in sql
    assert "ORDER BY created_at ASC" in sql
    assert params == {
        "limit": 10,
        "category": "CHAIR",
        "status": "pending",
        "route": "ai_agent",
    }


def test_save_decision_updates_status_verdict_and_decided_at():
    session = RecordingSession([ScalarResult(None)])
    repo = AmazonListingPendingReviewV2Repository(session)

    repo.save_decision(
        review_id=42,
        decision="approved",
        reviewer="attribute_review_agent",
        verdict={"verdict": "correct", "reason": "evidence matched"},
        review_status="completed",
    )

    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "UPDATE amz_listing_pending_review_v2" in sql
    assert "review_status = :review_status" in sql
    assert "verdict = :verdict" in sql
    assert "reviewer = :reviewer" in sql
    assert "decided_at = NOW()" in sql
    assert params["review_id"] == 42
    assert params["review_status"] == "completed"
    assert '"correct"' in params["verdict"]


def test_list_approved_for_sku_returns_only_approved_decisions():
    row = {
        "id": 7,
        "category": "CHAIR",
        "sku": "SKU1",
        "parent_sku": None,
        "path_key": "frame.color",
        "path_key_version": "v2_path_keys_2026_06",
        "attribute": "frame",
        "display_label": "Frame Color",
        "value": '"walnut"',
        "evidence": "matte walnut frame",
        "confidence_label": "medium",
        "confidence_score": 45,
        "route": "ai_agent",
        "review_status": "completed",
        "reviewer": "attribute_review_agent",
        "verdict": '{"verdict": "correct"}',
        "decided_at": None,
        "created_at": None,
        "updated_at": None,
    }
    session = RecordingSession([MappingRows([row])])
    repo = AmazonListingPendingReviewV2Repository(session)

    rows = repo.list_approved_for_sku(category="CHAIR", sku="SKU1")

    assert len(rows) == 1
    assert rows[0]["path_key"] == "frame.color"
    assert rows[0]["review_status"] == "completed"
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "review_status = 'completed'" in sql
    assert "category = :category" in sql
    assert "sku = :sku" in sql
    assert params == {"category": "CHAIR", "sku": "SKU1"}


def test_get_path_accuracy_aggregates_completed_decisions_by_path_key():
    session = RecordingSession([MappingRows([{"accuracy": 0.8}])])
    repo = AmazonListingPendingReviewV2Repository(session)

    accuracy = repo.get_path_accuracy("CHAIR", "frame.color", min_samples=10)

    assert accuracy == 0.8
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "path_key = :path_key" in sql
    assert "review_status = 'completed'" in sql
    assert "category = :product_type" in sql
    assert params == {
        "product_type": "CHAIR",
        "path_key": "frame.color",
        "min_samples": 10,
    }
