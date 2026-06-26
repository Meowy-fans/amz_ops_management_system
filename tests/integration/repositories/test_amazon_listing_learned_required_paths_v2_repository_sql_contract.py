"""SQL contract tests for V2 learned required paths repository."""

from src.repositories.amazon_listing_learned_required_paths_v2_repository import (
    AmazonListingLearnedRequiredPathsV2Repository,
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


def test_upsert_learned_inserts_new_path_with_sample_count_one():
    session = RecordingSession([ScalarResult(11)])
    repo = AmazonListingLearnedRequiredPathsV2Repository(session)

    review_id = repo.upsert_learned(
        category="CHAIR",
        path_key="frame_material",
        path_key_version="v2_path_keys_2026_06",
        attribute="frame_material",
        source_submission_id=42,
    )

    assert review_id == 11
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "INSERT INTO amz_listing_learned_required_paths_v2" in sql
    assert "ON CONFLICT (category, path_key, path_key_version) DO UPDATE" in sql
    assert "sample_count = amz_listing_learned_required_paths_v2.sample_count + 1" in sql
    assert "last_seen_at = NOW()" in sql
    assert params["category"] == "CHAIR"
    assert params["path_key"] == "frame_material"
    assert params["source_submission_id"] == 42


def test_list_for_category_returns_path_keys_ordered():
    row = {
        "id": 1,
        "category": "CHAIR",
        "path_key": "frame_material",
        "path_key_version": "v2_path_keys_2026_06",
        "attribute": "frame_material",
        "source_submission_id": 42,
        "sample_count": 3,
        "first_seen_at": None,
        "last_seen_at": None,
    }
    session = RecordingSession([MappingRows([row])])
    repo = AmazonListingLearnedRequiredPathsV2Repository(session)

    paths = repo.list_for_category(category="CHAIR")

    assert paths == ["frame_material"]
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "category = :category" in sql
    assert "ORDER BY path_key ASC" in sql
    assert params == {"category": "CHAIR"}


def test_list_for_category_and_paths_filters_by_path_key_set():
    row = {
        "id": 1,
        "category": "CHAIR",
        "path_key": "frame_material",
        "path_key_version": "v2_path_keys_2026_06",
        "attribute": "frame_material",
        "source_submission_id": 42,
        "sample_count": 2,
        "first_seen_at": None,
        "last_seen_at": None,
    }
    session = RecordingSession([MappingRows([row])])
    repo = AmazonListingLearnedRequiredPathsV2Repository(session)

    paths = repo.list_for_category_and_paths(
        category="CHAIR",
        path_keys=["frame_material", "seat_material_type"],
    )

    assert paths == ["frame_material"]
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "path_key = ANY(:path_keys)" in sql
    assert params["path_keys"] == ["frame_material", "seat_material_type"]
