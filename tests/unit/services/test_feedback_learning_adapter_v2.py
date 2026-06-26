"""Unit tests for V2 feedback learning adapter."""

from src.services.feedback_learning_adapter_v2 import FeedbackLearningAdapterV2


class FakeRepository:
    def __init__(self):
        self.upserts = []
        self.paths_by_category = {}
        self.paths_by_category_and_paths = {}

    def upsert_learned(self, category, path_key, path_key_version, attribute, source_submission_id):
        self.upserts.append((category, path_key, path_key_version, attribute, source_submission_id))
        return len(self.upserts)

    def list_for_category(self, category):
        return list(self.paths_by_category.get(category, []))

    def list_for_category_and_paths(self, category, path_keys):
        stored = self.paths_by_category_and_paths.get(category, [])
        return [p for p in stored if p in path_keys]


def test_learn_from_submission_extracts_90220_issues_and_upserts_path_keys():
    repo = FakeRepository()
    adapter = FeedbackLearningAdapterV2(repository=repo)
    submission = {
        "id": 42,
        "product_type": "CHAIR",
        "response_body": {
            "status": "INVALID",
            "issues": [
                {
                    "code": "90220",
                    "severity": "ERROR",
                    "message": "Required attribute missing",
                    "attributeNames": ["frame_material"],
                },
                {
                    "code": "90220",
                    "severity": "ERROR",
                    "message": "Required attribute missing",
                    "attributeNames": ["seat_material_type"],
                },
            ],
        },
    }

    count = adapter.learn_from_submission(submission)

    assert count == 2
    assert len(repo.upserts) == 2
    categories = [u[0] for u in repo.upserts]
    path_keys = [u[1] for u in repo.upserts]
    assert all(c == "CHAIR" for c in categories)
    assert set(path_keys) == {"frame_material", "seat_material_type"}
    assert all(u[4] == 42 for u in repo.upserts)


def test_learn_from_submission_skips_non_90220_issues():
    repo = FakeRepository()
    adapter = FeedbackLearningAdapterV2(repository=repo)
    submission = {
        "id": 42,
        "product_type": "CHAIR",
        "response_body": {
            "issues": [
                {"code": "90211", "attributeNames": ["item_name"]},
                {"code": "90220", "attributeNames": ["frame_material"]},
            ],
        },
    }

    count = adapter.learn_from_submission(submission)

    assert count == 1
    assert repo.upserts[0][1] == "frame_material"


def test_learn_from_submission_handles_missing_issues_array():
    repo = FakeRepository()
    adapter = FeedbackLearningAdapterV2(repository=repo)
    submission = {"id": 42, "product_type": "CHAIR", "response_body": {}}

    count = adapter.learn_from_submission(submission)

    assert count == 0
    assert repo.upserts == []


def test_learn_from_submission_skips_issues_without_attribute_names():
    repo = FakeRepository()
    adapter = FeedbackLearningAdapterV2(repository=repo)
    submission = {
        "id": 42,
        "product_type": "CHAIR",
        "response_body": {
            "issues": [
                {"code": "90220", "message": "missing something"},
            ],
        },
    }

    count = adapter.learn_from_submission(submission)

    assert count == 0
    assert repo.upserts == []


def test_get_learned_required_paths_returns_path_keys_for_category():
    repo = FakeRepository()
    repo.paths_by_category["CHAIR"] = ["frame_material", "seat_material_type"]
    adapter = FeedbackLearningAdapterV2(repository=repo)

    paths = adapter.get_learned_required_paths(category="CHAIR")

    assert paths == ["frame_material", "seat_material_type"]


def test_get_learned_required_paths_returns_empty_for_unknown_category():
    repo = FakeRepository()
    adapter = FeedbackLearningAdapterV2(repository=repo)

    paths = adapter.get_learned_required_paths(category="UNKNOWN")

    assert paths == []


def test_learn_from_submission_uses_default_path_key_version_when_missing():
    repo = FakeRepository()
    adapter = FeedbackLearningAdapterV2(repository=repo)
    submission = {
        "id": 7,
        "product_type": "CHAIR",
        "response_body": {
            "issues": [
                {"code": "90220", "attributeNames": ["frame_material"]},
            ],
        },
    }

    adapter.learn_from_submission(submission)

    _, _, path_key_version, _, _ = repo.upserts[0]
    assert path_key_version == "v2_path_keys_2026_06"


class FakeSubmissionRepo:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def list_submissions_with_issue_code(self, product_type, issue_code, limit=100):
        self.calls.append((product_type, issue_code, limit))
        return list(self._rows)


def test_learn_from_recent_submissions_scans_submissions_and_upserts_paths():
    repo = FakeRepository()
    submission_repo = FakeSubmissionRepo([
        {
            "id": 1,
            "product_type": "CHAIR",
            "response_body": {
                "issues": [{"code": "90220", "attributeNames": ["frame_material"]}],
            },
        },
        {
            "id": 2,
            "product_type": "CHAIR",
            "response_body": {
                "issues": [{"code": "90220", "attributeNames": ["seat_material_type"]}],
            },
        },
    ])
    adapter = FeedbackLearningAdapterV2(
        repository=repo,
        submission_repo=submission_repo,
    )

    summary = adapter.learn_from_recent_submissions(category="CHAIR", limit=50)

    assert summary == {"submissions_scanned": 2, "paths_learned": 2}
    assert len(repo.upserts) == 2
    assert submission_repo.calls == [("CHAIR", "90220", 50)]


def test_learn_from_recent_submissions_returns_zero_when_no_submissions():
    repo = FakeRepository()
    submission_repo = FakeSubmissionRepo([])
    adapter = FeedbackLearningAdapterV2(
        repository=repo,
        submission_repo=submission_repo,
    )

    summary = adapter.learn_from_recent_submissions(category="CHAIR")

    assert summary == {"submissions_scanned": 0, "paths_learned": 0}
    assert repo.upserts == []
