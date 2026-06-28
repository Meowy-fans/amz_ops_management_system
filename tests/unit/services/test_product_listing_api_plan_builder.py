"""Unit tests for API plan builder variation hierarchy integration."""

from src.services.amazon_variation_resolver import VariationResolutionResult
from src.services.product_listing_api_plan_builder import ProductListingAPIPlanBuilder
from src.services.requirement_models_v2 import (
    PayloadBuildPlan,
    RequirementNode,
    RequirementTree,
    ResolutionNode,
)
from src.services.variation_hierarchy_probe import VariationHierarchyProbeResult


class FakeProductListingRepo:
    def get_meow_skus_by_vendor_skus(self, vendor_skus):
        return {"VENDOR-1": "CHILD-1"}


class FakeListingLogRepo:
    def find_log_for_family(self, skus):
        return {"parent_sku": "PARENT-1", "variation_theme": "Color"}

    def get_family_details_by_parent(self, parent_sku):
        return [{"meow_sku": "CHILD-1", "variation_attributes": {"color_name": "Red"}}]


class FakeVariationResolver:
    def resolve_append_child(self, **kwargs):
        return VariationResolutionResult(
            mode="append_child",
            decision="passed",
            variation_theme=kwargs["existing_theme"],
            parent_sku=kwargs["parent_sku"],
            child_attributes={
                kwargs["new_child_data"]["meow_sku"]: {"color_name": "White"}
            },
            audit_run_id=99,
            existing_family_snapshot={
                "parent_sku": kwargs["parent_sku"],
                "children": kwargs["existing_children"],
            },
        )


class FakeProbe:
    def probe_parent(self, parent_sku):
        return VariationHierarchyProbeResult(
            parent_sku=parent_sku,
            probe_status="facts_collected",
            parent_asin="B012345678",
            child_asins=["B000000001"],
            online_sibling_facts=[
                {
                    "asin": "B000000001",
                    "variation_attributes": {"color_name": "White"},
                }
            ],
        )


class FakeAuditRepo:
    def __init__(self):
        self.updates = []

    def update_run_audit(self, **kwargs):
        self.updates.append(kwargs)


class FakeService:
    def __init__(self):
        self.db = object()
        self.product_listing_repo = FakeProductListingRepo()
        self.listing_log_repo = FakeListingLogRepo()
        self._variation_resolver_instance = FakeVariationResolver()
        self._variation_hierarchy_probe_instance = FakeProbe()
        self._variation_resolution_repo_instance = FakeAuditRepo()


class FakeShadowAdapter:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "sku": kwargs["sku"],
            "status": "shadow_built",
            "submission_id": 44,
        }


class FakeReviewManager:
    def __init__(self):
        self.plans = []

    def persist_pending_plan(self, plan):
        self.plans.append(plan)
        return 33


class FakeCoverageResult:
    blocked = True
    review_required = ["included_components"]
    blocking_codes = ["NEEDS_REVIEW_REQUIRED_ATTRIBUTE"]
    warning_codes = []
    findings = [{"code": "NEEDS_REVIEW_REQUIRED_ATTRIBUTE"}]
    missing_required = []
    low_confidence_required = []
    defaulted_required = []
    covered_required = ["included_components"]


class FakeV2Engine:
    def __init__(self, payload_build_plan):
        self.payload_build_plan = payload_build_plan
        self.calls = []

    def build_read_only_plan_from_draft(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload_build_plan


class FakeReviewAdapterV2:
    def __init__(self, overrides=None):
        self.calls = []
        self.overrides = overrides or {}

    def persist_pending_paths(self, **kwargs):
        self.calls.append(kwargs)
        return 2

    def build_overrides_from_decisions(self, category, sku):
        return dict(self.overrides)


def test_append_child_blocks_when_online_hierarchy_has_duplicate_signature():
    service = FakeService()
    builder = ProductListingAPIPlanBuilder(service)

    result = builder._resolve_existing_parent_append(
        product_data={
            "meow_sku": "NEW-1",
            "raw_data": {"associateProductList": ["VENDOR-1"]},
        },
        product_type="CABINET",
    )

    assert result.decision == "blocked"
    assert result.blocking_codes == ["DUPLICATE_ONLINE_VARIATION_ATTRIBUTES"]
    assert result.child_attributes == {}
    assert service._variation_resolution_repo_instance.updates[0]["run_id"] == 99
    assert (
        service._variation_resolution_repo_instance.updates[0]["decision"]
        == "blocked"
    )


def test_review_only_attribute_coverage_block_is_persisted_as_needs_review():
    service = FakeService()
    service._review_manager_instance = FakeReviewManager()
    builder = ProductListingAPIPlanBuilder(service)
    plan = {"sku": "SKU1", "product_type": "CHAIR"}

    result = builder._coverage_result("SKU1", plan, FakeCoverageResult())

    assert result["status"] == "needs_review"
    assert result["review_id"] == 33
    assert result["review_required"] == ["included_components"]
    assert service._review_manager_instance.plans == [plan]


def test_v2_shadow_result_is_skipped_by_default():
    service = FakeService()
    service._listing_payload_shadow_adapter_v2_instance = FakeShadowAdapter()
    builder = ProductListingAPIPlanBuilder(service)

    result = builder._record_v2_shadow_result(
        product_type="CHAIR",
        sku="SKU1",
        v1_plan={"attributes": {"item_name": [{"value": "Chair"}]}},
        v1_status="plan_generated",
    )

    assert result is None
    assert service._listing_payload_shadow_adapter_v2_instance.calls == []


def test_v2_shadow_result_runs_when_shadow_mode_enabled():
    service = FakeService()
    service.listing_payload_engine_mode = "shadow"
    service._listing_payload_shadow_adapter_v2_instance = FakeShadowAdapter()
    builder = ProductListingAPIPlanBuilder(service)

    result = builder._record_v2_shadow_result(
        product_type="CHAIR",
        sku="SKU1",
        v1_plan={"attributes": {"item_name": [{"value": "Chair"}]}},
        v1_status="plan_generated",
    )

    assert result["status"] == "shadow_built"
    assert service._listing_payload_shadow_adapter_v2_instance.calls == [
        {
            "product_type": "CHAIR",
            "sku": "SKU1",
            "v1_plan": {"attributes": {"item_name": [{"value": "Chair"}]}},
            "v1_status": "plan_generated",
        }
    ]


def test_v2_listing_plan_uses_engine_attributes_without_v1_coverage():
    service = FakeService()
    service.listing_payload_engine_mode = "v2"
    payload_build_plan = _payload_build_plan(
        attributes={"item_name": [{"value": "Chair"}]},
        findings=[],
    )
    service._listing_payload_engine_v2_instance = FakeV2Engine(payload_build_plan)
    service._review_adapter_v2_instance = FakeReviewAdapterV2()
    builder = ProductListingAPIPlanBuilder(service)
    draft = type("Draft", (), {"product_type": "CHAIR", "sku": "SKU1"})()

    plan, coverage = builder._build_listing_plan(
        draft,
        payload_builder=object(),
    )

    assert plan["listing_payload_engine"] == "v2"
    assert plan["attributes"] == {"item_name": [{"value": "Chair"}]}
    assert coverage.blocked is False
    assert service._listing_payload_engine_v2_instance.calls[0]["draft"] is draft
    assert service._listing_payload_engine_v2_instance.calls[0]["overrides"] is None


def test_v2_listing_plan_passes_approved_overrides_to_engine():
    service = FakeService()
    service.listing_payload_engine_mode = "v2"
    overrides = {
        "item_shape.value": {
            "value": "rectangular",
            "source": "review_override",
            "review_status": "completed",
        }
    }
    service._review_adapter_v2_instance = FakeReviewAdapterV2(overrides=overrides)
    payload_build_plan = _payload_build_plan(
        attributes={"item_name": [{"value": "Chair"}]},
        findings=[],
    )
    service._listing_payload_engine_v2_instance = FakeV2Engine(payload_build_plan)
    builder = ProductListingAPIPlanBuilder(service)
    draft = type("Draft", (), {"product_type": "CHAIR", "sku": "SKU1"})()

    builder._build_listing_plan(draft, payload_builder=object())

    assert service._listing_payload_engine_v2_instance.calls[0]["overrides"] == overrides


def test_v2_review_only_coverage_persists_path_level_pending_review():
    service = FakeService()
    service._review_adapter_v2_instance = FakeReviewAdapterV2()
    payload_build_plan = _payload_build_plan(
        attributes={"item_name": [{"value": "Chair"}]},
        findings=[
            {
                "code": "NEEDS_REVIEW_REQUIRED_ATTRIBUTE",
                "path_key": "item_shape.value",
                "severity": "ERROR",
                "blocking": True,
            }
        ],
        pending_review_paths=["item_shape.value"],
    )
    builder = ProductListingAPIPlanBuilder(service)
    result = builder._coverage_result_v2(
        "SKU1",
        {
            "sku": "SKU1",
            "product_type": "CHAIR",
            "attributes": {
                "child_parent_sku_relationship": [{"parent_sku": "PARENT-1"}]
            },
        },
        type(
            "Coverage",
            (),
            {
                "payload_build_plan": payload_build_plan,
                "review_required": ["item_shape.value"],
                "blocking_codes": ["NEEDS_REVIEW_REQUIRED_ATTRIBUTE"],
                "warning_codes": [],
                "findings": payload_build_plan.findings,
            },
        )(),
    )

    assert result["status"] == "needs_review"
    assert result["review_id"] == 2
    assert service._review_adapter_v2_instance.calls[0]["parent_sku"] == "PARENT-1"
    assert service._review_adapter_v2_instance.calls[0]["path_key_version"] == (
        "v2_path_keys_2026_06"
    )


def _payload_build_plan(
    attributes,
    findings,
    pending_review_paths=None,
):
    requirement_tree = RequirementTree(
        product_type="CHAIR",
        root=RequirementNode(
            path_key="$",
            schema_path="$",
            name="$",
            shape="object",
        ),
        required_paths=["item_name"],
    )
    return PayloadBuildPlan(
        sku="SKU1",
        product_type="CHAIR",
        attributes=attributes,
        requirement_tree=requirement_tree,
        resolution_tree=ResolutionNode(path_key="$"),
        covered_required_paths=["item_name"],
        pending_review_paths=pending_review_paths or [],
        findings=findings,
    )
