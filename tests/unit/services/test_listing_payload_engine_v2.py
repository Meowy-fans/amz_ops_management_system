"""Tests for V2 read-only payload engine orchestration."""

from src.models.amazon_listing import AmazonListingDraft, ListingContent, ListingOffer
from src.models.product import StandardProduct
from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2


class FakeProductRepo:
    def get_full_product_data(self, sku):
        assert sku == "SKU1"
        return {"sku": "SKU1"}


class FakeDraftBuilder:
    def build(self, product_data, product_type):
        assert product_data == {"sku": "SKU1"}
        product = StandardProduct(
            sku="SKU1",
            vendor_sku="GIGA1",
            vendor_source="giga",
            attributes={"Frame Color": "Black"},
        )
        return AmazonListingDraft(
            sku="SKU1",
            vendor_sku="GIGA1",
            product_type=product_type,
            standard_product=product,
            content=ListingContent(title="Black Chair"),
            offer=ListingOffer(price=99.99, quantity=2),
        )


class FakeSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "CHAIR"
        return {
            "required_properties": ["item_name", "frame"],
            "schema_json": {
                "properties": {
                    "item_name": {
                        "items": {
                            "required": ["language_tag", "value"],
                            "properties": {
                                "language_tag": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        }
                    },
                    "frame": {
                        "items": {
                            "required": ["color"],
                            "properties": {
                                "color": {
                                    "items": {
                                        "required": ["language_tag", "value"],
                                        "properties": {
                                            "language_tag": {"type": "string"},
                                            "value": {"enum": ["Black", "Brown"]},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
        }


def test_engine_builds_read_only_payload_plan_with_coverage():
    engine = ListingPayloadEngineV2(
        db=object(),
        schema_service=FakeSchemaService(),
        product_repo=FakeProductRepo(),
        draft_builder=FakeDraftBuilder(),
    )
    rules = {
        "version": "rules_v1",
        "attributes": {
            "item_name": {
                "sources": [{"path": "content.title"}],
            },
            "frame": {
                "children": {
                    "color": {
                        "transform": "enum",
                        "sources": [{"path": "product.attributes.Frame Color"}],
                    }
                }
            },
        },
    }

    plan = engine.build_read_only_plan("CHAIR", "SKU1", rules)

    assert plan.sku == "SKU1"
    assert plan.product_type == "CHAIR"
    assert plan.attributes == {
        "item_name": [{"language_tag": "en_US", "value": "Black Chair"}],
        "frame": [{"color": [{"language_tag": "en_US", "value": "Black"}]}],
    }
    assert plan.covered_required_paths == [
        "item_name",
        "item_name.value",
        "frame",
        "frame.color",
        "frame.color.value",
    ]
    assert plan.missing_required_paths == []
    assert plan.findings == []
