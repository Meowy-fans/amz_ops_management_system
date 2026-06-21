"""Unit tests for API plan builder variation hierarchy integration."""

from src.services.amazon_variation_resolver import VariationResolutionResult
from src.services.product_listing_api_plan_builder import ProductListingAPIPlanBuilder
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
        self.product_listing_repo = FakeProductListingRepo()
        self.listing_log_repo = FakeListingLogRepo()
        self._variation_resolver_instance = FakeVariationResolver()
        self._variation_hierarchy_probe_instance = FakeProbe()
        self._variation_resolution_repo_instance = FakeAuditRepo()


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
