"""Unit tests for V2 path-level review adapter."""

from src.services.requirement_models_v2 import ResolutionNode
from src.services.review_adapter_v2 import ReviewAdapterV2


class FakeRepository:
    def __init__(self):
        self.upserts = []
        self.pending_rows = []
        self.saved = []
        self.approved_rows = []

    def upsert_pending_paths(self, items):
        self.upserts.append(items)
        return [i + 1 for i in range(len(items))]

    def list_pending(self, category=None, status="pending", route=None, limit=50):
        rows = list(self.pending_rows)
        if route:
            rows = [r for r in rows if r.get("route") == route]
        return rows

    def save_decision(self, review_id, decision, reviewer, verdict, review_status):
        self.saved.append((review_id, decision, reviewer, verdict, review_status))

    def list_approved_for_sku(self, category, sku):
        return list(self.approved_rows)


class FakeVerdict:
    def __init__(self, verdict, reason="matched"):
        self.verdict = verdict
        self._dict = {"verdict": verdict, "reason": reason}

    def as_dict(self):
        return self._dict


class FakeReviewAgent:
    def __init__(self, verdict="correct"):
        self.verdict = verdict
        self.calls = []

    def review(self, plan_snapshot, item):
        self.calls.append(item)
        return FakeVerdict(self.verdict)


def test_extract_pending_paths_collects_ai_agent_and_human_leaf_nodes():
    resolution_root = _root(
        ResolutionNode(
            path_key="frame",
            children=[
                ResolutionNode(
                    path_key="frame.color",
                    value="walnut",
                    source="llm",
                    evidence="matte walnut frame",
                    confidence="medium",
                    confidence_score=45,
                    review_route="ai_agent",
                    blocking=True,
                    blocking_codes=["LOW_CONFIDENCE_REQUIRED_ATTRIBUTE"],
                ),
                ResolutionNode(
                    path_key="frame.material",
                    value="wood",
                    source="llm",
                    evidence="solid wood",
                    confidence="medium",
                    confidence_score=55,
                    review_route="auto_approved",
                    blocking=False,
                ),
            ],
        ),
        ResolutionNode(
            path_key="brand",
            value="SomeBrand",
            source="llm",
            evidence="supplier spec",
            confidence="medium",
            confidence_score=0,
            review_route="human",
            blocking=True,
            blocking_codes=["LOW_CONFIDENCE_REQUIRED_ATTRIBUTE"],
        ),
        ResolutionNode(
            path_key="item_name",
            value=None,
            source="",
            confidence="low",
            review_route="human",
            blocking=True,
            blocking_codes=["MISSING_REQUIRED_ATTRIBUTE_RULE"],
        ),
    )

    items = ReviewAdapterV2._extract_pending_paths(resolution_root)

    path_keys = [item["path_key"] for item in items]
    assert path_keys == ["frame.color", "brand"]
    color_item = items[0]
    assert color_item["attribute"] == "frame"
    assert color_item["route"] == "ai_agent"
    assert color_item["value"] == "walnut"
    assert color_item["evidence"] == "matte walnut frame"
    assert color_item["confidence_score"] == 45


def test_persist_pending_paths_upserts_extracted_items_to_repository():
    repo = FakeRepository()
    adapter = ReviewAdapterV2(repository=repo)
    resolution_root = _root(
        ResolutionNode(
            path_key="frame.color",
            value="walnut",
            source="llm",
            evidence="matte walnut frame",
            confidence="medium",
            confidence_score=45,
            review_route="ai_agent",
            blocking=True,
            blocking_codes=["LOW_CONFIDENCE_REQUIRED_ATTRIBUTE"],
        )
    )

    count = adapter.persist_pending_paths(
        category="CHAIR",
        sku="SKU1",
        parent_sku=None,
        path_key_version="v2_path_keys_2026_06",
        plan_snapshot={"sku": "SKU1"},
        resolution_root=resolution_root,
    )

    assert count == 1
    assert len(repo.upserts) == 1
    item = repo.upserts[0][0]
    assert item["category"] == "CHAIR"
    assert item["sku"] == "SKU1"
    assert item["path_key"] == "frame.color"
    assert item["path_key_version"] == "v2_path_keys_2026_06"
    assert item["plan_snapshot"] == {"sku": "SKU1"}
    assert item["route"] == "ai_agent"


def test_persist_pending_paths_returns_zero_when_no_pending_leaves():
    repo = FakeRepository()
    adapter = ReviewAdapterV2(repository=repo)
    resolution_root = _root(
        ResolutionNode(
            path_key="frame.color",
            value="walnut",
            source="llm",
            evidence="matte walnut frame",
            confidence="medium",
            confidence_score=80,
            review_route="auto_approved",
            blocking=False,
        )
    )

    count = adapter.persist_pending_paths(
        category="CHAIR",
        sku="SKU1",
        parent_sku=None,
        path_key_version="v2_path_keys_2026_06",
        plan_snapshot={"sku": "SKU1"},
        resolution_root=resolution_root,
    )

    assert count == 0
    assert repo.upserts == []


def test_review_pending_paths_runs_ai_agent_on_ai_route_items_only():
    repo = FakeRepository()
    repo.pending_rows = [
        {
            "id": 1,
            "category": "CHAIR",
            "sku": "SKU1",
            "path_key": "frame.color",
            "attribute": "frame",
            "value": "walnut",
            "evidence": "matte walnut frame",
            "route": "ai_agent",
            "review_status": "pending",
            "plan_snapshot": {"sku": "SKU1"},
        },
        {
            "id": 2,
            "category": "CHAIR",
            "sku": "SKU1",
            "path_key": "brand",
            "attribute": "brand",
            "value": "SomeBrand",
            "evidence": "supplier spec",
            "route": "human",
            "review_status": "pending",
            "plan_snapshot": {"sku": "SKU1"},
        },
    ]
    agent = FakeReviewAgent(verdict="correct")
    adapter = ReviewAdapterV2(repository=repo, review_agent=agent)

    summary = adapter.review_pending_paths(category="CHAIR", limit=10)

    assert summary["reviewed"] == 1
    assert summary["human_required"] == 1
    assert len(agent.calls) == 1
    assert agent.calls[0]["path_key"] == "frame.color"
    assert len(repo.saved) == 1
    review_id, decision, reviewer, verdict, status = repo.saved[0]
    assert review_id == 1
    assert decision == "approved"
    assert reviewer == "attribute_review_agent"
    assert status == "completed"


def test_review_pending_paths_marks_needs_human_when_agent_uncertain():
    repo = FakeRepository()
    repo.pending_rows = [
        {
            "id": 1,
            "category": "CHAIR",
            "sku": "SKU1",
            "path_key": "frame.color",
            "attribute": "frame",
            "value": "walnut",
            "evidence": "matte walnut frame",
            "route": "ai_agent",
            "review_status": "pending",
            "plan_snapshot": {"sku": "SKU1"},
        },
    ]
    agent = FakeReviewAgent(verdict="uncertain")
    adapter = ReviewAdapterV2(repository=repo, review_agent=agent)

    summary = adapter.review_pending_paths(category="CHAIR", limit=10)

    assert summary["reviewed"] == 1
    assert summary["human_required"] == 1
    assert len(repo.saved) == 1
    _, decision, _, _, status = repo.saved[0]
    assert decision == "needs_human"
    assert status == "in_progress"


def test_build_overrides_from_decisions_returns_path_keyed_override_map():
    repo = FakeRepository()
    repo.approved_rows = [
        {
            "path_key": "frame.color",
            "value": "walnut",
            "evidence": "matte walnut frame",
            "confidence_label": "medium",
            "confidence_score": 45,
            "route": "ai_agent",
            "review_status": "completed",
        },
        {
            "path_key": "seat.material_type",
            "value": "linen",
            "evidence": "linen cushion",
            "confidence_label": "medium",
            "confidence_score": 40,
            "route": "ai_agent",
            "review_status": "completed",
        },
    ]
    adapter = ReviewAdapterV2(repository=repo)

    overrides = adapter.build_overrides_from_decisions(category="CHAIR", sku="SKU1")

    assert set(overrides.keys()) == {"frame.color", "seat.material_type"}
    color_override = overrides["frame.color"]
    assert color_override["value"] == "walnut"
    assert color_override["evidence"] == "matte walnut frame"
    assert color_override["confidence"] == "medium"
    assert color_override["review_status"] == "completed"
    assert color_override["source"] == "review_override"


class FakeEngine:
    def __init__(self):
        self.calls = []

    def build_read_only_plan(self, product_type, sku, rules, overrides=None):
        self.calls.append((product_type, sku, rules, overrides))

        class FakePlan:
            def __init__(self):
                self.sku = sku
                self.product_type = product_type
                self.findings = []
                self.missing_required_paths = []
                self.pending_review_paths = []
                self.safe_default_paths = []

        return FakePlan()


class FakeRuleLoader:
    def __init__(self):
        self.calls = []

    def load(self, product_type):
        self.calls.append(product_type)
        return {"product_type": product_type, "attributes": {}}


def test_submit_reviewed_paths_rebuilds_plan_with_overrides_for_completed_skus():
    repo = FakeRepository()
    repo.completed_skus = [
        {"category": "CHAIR", "sku": "SKU1", "parent_sku": None},
    ]
    repo.approved_rows = [
        {
            "path_key": "frame.color",
            "value": "walnut",
            "evidence": "matte walnut frame",
            "confidence_label": "medium",
            "confidence_score": 45,
            "route": "ai_agent",
            "review_status": "completed",
        },
    ]

    class RepoWithCompletedSkus(FakeRepository):
        def __init__(self):
            super().__init__()
            self.completed_skus = [
                {"category": "CHAIR", "sku": "SKU1", "parent_sku": None},
            ]

        def list_completed_skus(self, category=None, limit=50):
            return list(self.completed_skus)

    repo = RepoWithCompletedSkus()
    repo.approved_rows = [
        {
            "path_key": "frame.color",
            "value": "walnut",
            "evidence": "matte walnut frame",
            "confidence_label": "medium",
            "confidence_score": 45,
            "route": "ai_agent",
            "review_status": "completed",
        },
    ]
    engine = FakeEngine()
    rule_loader = FakeRuleLoader()
    adapter = ReviewAdapterV2(
        repository=repo,
        engine=engine,
        rule_loader=rule_loader,
    )

    results = adapter.submit_reviewed_paths(category="CHAIR", dry_run=True)

    assert len(results) == 1
    assert results[0]["sku"] == "SKU1"
    assert results[0]["status"] == "dry_run_preview"
    assert len(engine.calls) == 1
    product_type, sku, rules, overrides = engine.calls[0]
    assert product_type == "CHAIR"
    assert sku == "SKU1"
    assert "frame.color" in overrides
    assert rule_loader.calls == ["CHAIR"]


def test_attribute_derived_from_path_key_first_segment():
    resolution_root = _root(
        ResolutionNode(
            path_key="maximum_weight_recommendation.value",
            value=250,
            source="product.attributes.Weight Capacity",
            evidence="250 pounds capacity",
            confidence="medium",
            confidence_score=45,
            review_route="ai_agent",
            blocking=True,
            blocking_codes=["LOW_CONFIDENCE_REQUIRED_ATTRIBUTE"],
        )
    )

    items = ReviewAdapterV2._extract_pending_paths(resolution_root)

    assert items[0]["attribute"] == "maximum_weight_recommendation"
    assert items[0]["path_key"] == "maximum_weight_recommendation.value"


def _root(*children: ResolutionNode) -> ResolutionNode:
    return ResolutionNode(
        path_key="CHAIR",
        children=list(children),
    )
