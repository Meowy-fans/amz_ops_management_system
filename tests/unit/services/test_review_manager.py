"""Unit tests for pending attribute review manager."""

from src.services.review_manager import ReviewManager


class FakeRepository:
    def __init__(self):
        self.upserts = []
        self.rows = []
        self.saved = []

    def upsert_pending(self, **kwargs):
        self.upserts.append(kwargs)
        return 7

    def list_reviews(self, category=None, status=None, limit=50):
        return list(self.rows)

    def save_decisions(self, review_id, decisions, status):
        self.saved.append((review_id, decisions, status))


class FakeAgent:
    def review(self, plan_snapshot, pending_item):
        class Verdict:
            verdict = "correct"

            def as_dict(self):
                return {"verdict": "correct", "reason": "matched"}

        return Verdict()


class FakeCoverageGate:
    def __init__(self, blocked=False):
        self.blocked = blocked

    def evaluate(self, plan):
        class Result:
            def __init__(self, blocked):
                self.blocked = blocked
                self.findings = []
                self.blocking_codes = []

        return Result(self.blocked)


class FakeSubmitter:
    def __init__(self):
        self.calls = []

    def submit(self, plans, dry_run=True, validation_only=False):
        self.calls.append((plans, dry_run, validation_only))
        return [{"sku": plans[0]["sku"], "status": "dry_run_preview"}]


def _pending_plan():
    return {
        "sku": "SKU1",
        "product_type": "CHAIR",
        "attributes": {"included_components": [{"value": "Chair"}]},
        "attribute_resolutions": {
            "included_components": {
                "attribute": "included_components",
                "value": "Chair",
                "level": "required",
                "shape": "list_value",
                "source": "llm",
                "evidence": "Chair included",
                "confidence": "medium",
                "state": "needs_manual_review",
                "review_status": "pending",
                "review_route": "ai_agent",
                "confidence_score": 45,
                "review_context": "Chair included in the package",
            }
        },
    }


def test_review_manager_persists_pending_required_llm_items():
    repo = FakeRepository()
    manager = ReviewManager(db=object(), repository=repo)

    review_id = manager.persist_pending_plan(_pending_plan())

    assert review_id == 7
    pending_items = repo.upserts[0]["pending_items"]
    assert pending_items[0]["attribute"] == "included_components"
    assert pending_items[0]["route"] == "ai_agent"
    assert pending_items[0]["context_text"] == "Chair included in the package"


def test_review_manager_completes_ai_agent_approved_items():
    repo = FakeRepository()
    repo.rows = [{
        "id": 7,
        "plan_snapshot": _pending_plan(),
        "pending_items": [{
            "attribute": "included_components",
            "value": "Chair",
            "evidence": "Chair included",
            "route": "ai_agent",
            "context_text": "Chair included in the package",
        }],
        "review_decisions": [],
    }]
    manager = ReviewManager(db=object(), repository=repo, review_agent=FakeAgent())

    result = manager.review_pending_attributes(category="CHAIR")

    assert result["reviewed"] == 1
    assert result["completed"] == 1
    assert repo.saved[0][2] == "completed"
    assert repo.saved[0][1][0]["decision"] == "approved"


def test_review_manager_submits_completed_plan_without_rerunning_resolver():
    repo = FakeRepository()
    repo.rows = [{
        "id": 7,
        "plan_snapshot": _pending_plan(),
        "pending_items": [],
        "review_decisions": [{
            "attribute": "included_components",
            "decision": "approved",
            "value": "Chair",
            "evidence": "Chair included",
        }],
    }]
    submitter = FakeSubmitter()
    manager = ReviewManager(
        db=object(),
        repository=repo,
        coverage_gate=FakeCoverageGate(blocked=False),
        submitter=submitter,
    )

    results = manager.submit_reviewed_plans(category="CHAIR", dry_run=True)

    assert results == [{"sku": "SKU1", "status": "dry_run_preview"}]
    submitted_plan = submitter.calls[0][0][0]
    resolution = submitted_plan["attribute_resolutions"]["included_components"]
    assert resolution["source"] == "review_override"
    assert resolution["review_status"] == "completed"
