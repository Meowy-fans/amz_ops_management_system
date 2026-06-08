"""Unit tests for API-native Amazon listing payload builder."""

from src.models.amazon_listing import AmazonListingDraft, ListingContent, ListingOffer
from src.models.product import DimensionSpec, InventorySpec, StandardProduct
from src.services.amazon_listing_payload_builder import AmazonListingPayloadBuilder


class FakeSchemaService:
    def get_valid_values(self, product_type, field_name):
        values = {
            "color": ["White", "Black"],
            "country_of_origin": ["CN", "US"],
        }
        return values.get(field_name)


def _product():
    return StandardProduct(
        sku="MEOW1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        images=["https://img.example/main.jpg", "https://img.example/alt.jpg"],
        attributes={
            "Main Color": "white",
            "Main Material": "MDF",
            "Product Style": "Modern",
            "mpn": "MPN1",
            "place_of_origin": "China",
        },
        dimensions=DimensionSpec(
            assembled_length=30,
            assembled_width=20,
            assembled_height=34,
            weight=55,
        ),
        inventory=InventorySpec(quantity=12),
    )


def test_build_plan_from_draft_without_excel_row():
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        standard_product=_product(),
        content=ListingContent(
            title="Modern Bathroom Cabinet",
            bullets=["Soft close doors", "Water resistant finish"],
            description="A modern cabinet for bathrooms.",
            search_terms="bathroom cabinet modern",
        ),
        offer=ListingOffer(price=199.99, quantity=12),
    )
    builder = AmazonListingPayloadBuilder(
        schema_service=FakeSchemaService(),
        marketplace_id="MARKET1",
    )

    plan = builder.build_plan(draft)

    assert plan["sku"] == "MEOW1"
    assert plan["product_type"] == "CABINET"
    attrs = plan["attributes"]
    assert attrs["item_name"] == [{"value": "Modern Bathroom Cabinet"}]
    assert attrs["bullet_point"] == [
        {"value": "Soft close doors"},
        {"value": "Water resistant finish"},
    ]
    assert attrs["color"] == [{"value": "White"}]
    assert attrs["country_of_origin"] == [{"value": "CN"}]
    assert attrs["main_product_image_locator"] == [
        {"media_location": "https://img.example/main.jpg"}
    ]
    assert attrs["other_product_image_locator_1"] == [
        {"media_location": "https://img.example/alt.jpg"}
    ]
    assert attrs["purchasable_offer"][0]["marketplace_id"] == "MARKET1"
    assert attrs["fulfillment_availability"][0]["quantity"] == 12
    assert attrs["item_depth_width_height"][0]["width"]["value"] == 30
    assert attrs["supplier_declared_has_product_identifier_exemption"] == [
        {"value": "Yes"}
    ]


def test_builder_omits_empty_optional_values():
    product = _product()
    product.images = []
    product.dimensions = None
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="HOME_MIRROR",
        standard_product=product,
        content=ListingContent(title="Mirror", bullets=[], description=""),
        offer=ListingOffer(price=None, quantity=0),
    )

    plan = AmazonListingPayloadBuilder().build_plan(draft)

    attrs = plan["attributes"]
    assert "main_product_image_locator" not in attrs
    assert "item_depth_width_height" not in attrs
    assert "purchasable_offer" not in attrs
