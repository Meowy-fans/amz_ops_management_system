"""Tests for V2 validation compare evaluator."""

from src.services.listing_payload_v2_validation_compare import (
    ListingPayloadV2ValidationCompare,
    ValidationCompareCase,
)
from src.services.requirement_models_v2 import PayloadBuildPlan, RequirementNode, RequirementTree
from src.services.validation_preview_v2 import ValidationPreviewResult, ValidationPreviewV2


class FakeEngine:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def build_read_only_plan(self, product_type, sku, rules, overrides=None):
        self.calls.append((product_type, sku, rules, overrides))
        return self.plan


class FakePreview:
    def __init__(self, result):
        self.result = result
        self.compare_calls = []

    def preview(self, plan):
        return self.result

    def compare(self, plan, result):
        self.compare_calls.append((plan, result))
        return ValidationPreviewV2().compare(plan, result)


class FakeReviewAdapter:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def build_overrides_from_decisions(self, category, sku):
        return dict(self.overrides)


class FakeRuleLoader:
    def load(self, product_type):
        return {"product_type": product_type, "attributes": {}}


class FakePlanBuilder:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def build_v2_payload_plan_for_sku(self, product_type, sku):
        self.calls.append((product_type, sku))
        return self.plan


def _plan(findings=None):
    root = RequirementNode(path_key="CHAIR", schema_path="$", name="CHAIR", shape="root")
    tree = RequirementTree(product_type="CHAIR", root=root, required_paths=[])
    return PayloadBuildPlan(
        sku="SKU1",
        product_type="CHAIR",
        attributes={"item_name": [{"value": "Chair"}]},
        requirement_tree=tree,
        findings=findings or [],
    )


def test_evaluate_returns_go_when_preview_clean_and_no_unexplained_amazon_only():
    plan = _plan()
    result = ValidationPreviewResult(
        sku="SKU1",
        product_type="CHAIR",
        status="validation_preview_passed",
        issues=[],
    )
    service = ListingPayloadV2ValidationCompare(
        db=object(),
        engine=FakeEngine(plan),
        preview=FakePreview(result),
        review_adapter=FakeReviewAdapter(),
        rule_loader=FakeRuleLoader(),
    )

    report = service.evaluate(
        cases=[ValidationCompareCase("CHAIR", "SKU1")],
    )

    assert report["status"] == "go"
    assert report["cases"][0]["decision"] == "go"
    assert report["cases"][0]["comparison"]["unexplained_amazon_only"] == 0


def test_evaluate_returns_no_go_for_unexplained_amazon_only_error():
    plan = _plan()
    result = ValidationPreviewResult(
        sku="SKU1",
        product_type="CHAIR",
        status="validation_preview_issues",
        issues=[
            {
                "code": "90220",
                "severity": "ERROR",
                "message": "Missing required",
                "attributeNames": ["frame_material"],
            }
        ],
    )
    service = ListingPayloadV2ValidationCompare(
        db=object(),
        engine=FakeEngine(plan),
        preview=FakePreview(result),
        review_adapter=FakeReviewAdapter(),
        rule_loader=FakeRuleLoader(),
    )

    report = service.evaluate(
        cases=[ValidationCompareCase("CHAIR", "SKU1")],
    )

    assert report["status"] == "no_go"
    assert report["cases"][0]["reasons"] == ["unexplained_amazon_only_issues"]


def test_evaluate_uses_review_overrides_when_building_plan():
    plan = _plan()
    result = ValidationPreviewResult(
        sku="SKU1",
        product_type="CHAIR",
        status="validation_preview_passed",
        issues=[],
    )
    engine = FakeEngine(plan)
    overrides = {"frame.color": {"value": "walnut"}}
    service = ListingPayloadV2ValidationCompare(
        db=object(),
        engine=engine,
        preview=FakePreview(result),
        review_adapter=FakeReviewAdapter(overrides=overrides),
        rule_loader=FakeRuleLoader(),
    )

    service.evaluate(cases=[ValidationCompareCase("CHAIR", "SKU1")])

    assert engine.calls[0][3] == overrides


def test_evaluate_uses_plan_builder_when_provided():
    plan = _plan()
    result = ValidationPreviewResult(
        sku="SKU1",
        product_type="CHAIR",
        status="validation_preview_passed",
        issues=[],
    )
    plan_builder = FakePlanBuilder(plan)
    service = ListingPayloadV2ValidationCompare(
        db=object(),
        engine=FakeEngine(plan),
        preview=FakePreview(result),
        plan_builder=plan_builder,
    )

    service.evaluate(cases=[ValidationCompareCase("CHAIR", "SKU1")])

    assert plan_builder.calls == [("CHAIR", "SKU1")]


def test_evaluate_ignores_coverage_ignore_required_amazon_only_issues():
    plan = _plan()
    result = ValidationPreviewResult(
        sku="SKU1",
        product_type="CABINET",
        status="validation_preview_issues",
        issues=[
            {
                "code": "90220",
                "severity": "ERROR",
                "message": "Missing required",
                "attributeNames": ["merchant_suggested_asin"],
            }
        ],
    )
    service = ListingPayloadV2ValidationCompare(
        db=object(),
        engine=FakeEngine(plan),
        preview=FakePreview(result),
        rule_loader=type(
            "Rules",
            (),
            {
                "load": staticmethod(
                    lambda product_type: {
                        "coverage_ignore_required": ["merchant_suggested_asin"]
                    }
                )
            },
        )(),
        plan_builder=FakePlanBuilder(plan),
    )

    report = service.evaluate(cases=[ValidationCompareCase("CABINET", "SKU1")])

    assert report["status"] == "go"
    assert report["cases"][0]["decision"] == "go"
