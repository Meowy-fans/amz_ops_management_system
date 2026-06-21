"""Unit tests for API-native Amazon listing payload builder."""

from pathlib import Path

from src.models.amazon_listing import AmazonListingDraft, ListingContent, ListingOffer
from src.models.product import DimensionSpec, InventorySpec, StandardProduct
from src.services.amazon_listing_payload_builder import AmazonListingPayloadBuilder


class FakeSchemaService:
    _REQUIRED_BY_TYPE = {
        "CABINET": ["fabric_type"],
        "HOME_MIRROR": ["fabric_type"],
    }

    def get_valid_values(self, product_type, field_name):
        values = {
            "color": ["White", "Black"],
            "country_of_origin": ["CN", "US", "MY"],
            "variation_theme": ["COLOR", "COLOR/SIZE"],
        }
        return values.get(field_name)

    def get_cached_valid_values(self, product_type, field_name):
        return self.get_valid_values(product_type, field_name)

    def get_required_properties(self, product_type):
        return self._REQUIRED_BY_TYPE.get(str(product_type or "").upper(), [])


class HomeMirrorAllowlistSchemaService(FakeSchemaService):
    def get_property_names(self, product_type):
        if str(product_type or "").upper() != "HOME_MIRROR":
            return []
        return [
            "item_name",
            "product_description",
            "bullet_point",
            "brand",
            "manufacturer",
            "part_number",
            "model_number",
            "item_type_keyword",
            "condition_type",
            "color",
            "material",
            "style",
            "country_of_origin",
            "main_product_image_locator",
            "other_product_image_locator_1",
            "purchasable_offer",
            "list_price",
            "fulfillment_availability",
            "item_weight",
            "model_name",
            "frame",
            "mounting_type",
            "is_assembly_required",
            "item_shape",
            "item_length_width",
            "included_components",
            "special_feature",
            "room_type",
            "number_of_items",
            "fabric_type",
            "supplier_declared_dg_hz_regulation",
            "externally_assigned_product_identifier",
            "supplier_declared_has_product_identifier_exemption",
        ]


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
    assert attrs["fabric_type"] == [{"value": "MDF"}]
    assert attrs["door"] == [
        {
            "style": [
                {
                    "value": "Shaker",
                    "language_tag": "en_US",
                    "marketplace_id": "MARKET1",
                }
            ],
            "marketplace_id": "MARKET1",
        }
    ]
    assert attrs["mounting_type"] == [{"value": "Freestanding"}]
    assert attrs["model_name"] == [{"value": "MPN1"}]
    assert attrs["number_of_items"] == [{"value": 1}]
    assert attrs["included_components"] == [{"value": "Cabinet"}]
    assert attrs["is_assembly_required"] == [{"value": "Yes"}]
    assert attrs["item_shape"] == [{"value": "Rectangular"}]
    assert attrs["room_type"] == [{"value": "Bathroom"}]
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
    assert attrs["item_width"] == [{"value": 30.0, "unit": "inches"}]
    assert "item_type_name" not in attrs
    assert "target_audience_base" not in attrs
    assert attrs["supplier_declared_has_product_identifier_exemption"] == [
        {"value": "Yes"}
    ]


def test_cabinet_variation_theme_is_aligned_to_schema_valid_value():
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        standard_product=_product(),
        content=ListingContent(title="Modern Bathroom Cabinet"),
        offer=ListingOffer(price=199.99, quantity=12),
    )
    draft.variation.parentage_level = "parent"
    draft.variation.variation_theme = "Color"

    plan = AmazonListingPayloadBuilder(
        schema_service=FakeSchemaService(),
        marketplace_id="MARKET1",
    ).build_plan(draft)

    assert plan["attributes"]["variation_theme"] == [{"name": "COLOR"}]


def test_ottoman_variation_theme_color_is_normalized_to_amazon_value():
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="OTTOMAN",
        standard_product=_product(),
        content=ListingContent(title="Ottoman Storage Bench"),
        offer=ListingOffer(price=123.34, quantity=12),
    )
    draft.variation.parentage_level = "parent"
    draft.variation.variation_theme = "Color"

    plan = AmazonListingPayloadBuilder(marketplace_id="MARKET1").build_plan(draft)

    assert plan["attributes"]["variation_theme"] == [{"name": "COLOR"}]


def test_ottoman_fabric_type_is_resolved_from_material_rules():
    product = _product()
    product.attributes["Main Material"] = "Linen"
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="OTTOMAN",
        standard_product=product,
        content=ListingContent(title="Ottoman Storage Bench"),
        offer=ListingOffer(price=123.34, quantity=12),
    )

    plan = AmazonListingPayloadBuilder(marketplace_id="MARKET1").build_plan(draft)

    assert plan["attributes"]["fabric_type"] == [{"value": "Linen"}]


def test_ottoman_removes_schema_inapplicable_attributes():
    product = _product()
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="OTTOMAN",
        standard_product=product,
        content=ListingContent(title="Ottoman Storage Bench"),
        offer=ListingOffer(price=123.34, quantity=12),
    )

    attrs = AmazonListingPayloadBuilder(marketplace_id="MARKET1").build_plan(draft)[
        "attributes"
    ]

    assert "item_type_name" not in attrs
    assert "item_depth" not in attrs
    assert "item_height" not in attrs
    assert "room_type" not in attrs
    assert "target_audience_base" not in attrs
    assert "item_width" in attrs


def test_cabinet_color_size_variation_uses_item_width_not_size_name():
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        standard_product=_product(),
        content=ListingContent(title="Modern Bathroom Cabinet"),
        offer=ListingOffer(price=199.99, quantity=12),
    )
    draft.variation.parentage_level = "child"
    draft.variation.variation_theme = "Color/Size"
    draft.variation.theme_attributes = {
        "color_name": "Black",
        "size_name": "30.00",
    }

    plan = AmazonListingPayloadBuilder(marketplace_id="MARKET1").build_plan(draft)
    attrs = plan["attributes"]

    assert attrs["variation_theme"] == [{"name": "COLOR/ITEM_WIDTH"}]
    assert attrs["color"] == [{"value": "Black"}]
    assert attrs["item_width"] == [{"value": 30.0, "unit": "inches"}]
    assert "size_name" not in attrs


def test_cabinet_size_variation_uses_item_width_theme():
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        standard_product=_product(),
        content=ListingContent(title="Modern Bathroom Cabinet"),
        offer=ListingOffer(price=199.99, quantity=12),
    )
    draft.variation.parentage_level = "child"
    draft.variation.variation_theme = "Size"
    draft.variation.theme_attributes = {"size_name": "30"}

    plan = AmazonListingPayloadBuilder(marketplace_id="MARKET1").build_plan(draft)
    attrs = plan["attributes"]

    assert attrs["variation_theme"] == [{"name": "ITEM_WIDTH"}]
    assert attrs["item_width"] == [{"value": 30.0, "unit": "inches"}]
    assert "size_name" not in attrs


def test_country_of_origin_maps_malaysia_to_iso_code():
    product = _product()
    product.attributes["place_of_origin"] = "Malaysia"
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        standard_product=product,
        content=ListingContent(title="Modern Bathroom Cabinet"),
        offer=ListingOffer(price=199.99, quantity=12),
    )

    plan = AmazonListingPayloadBuilder(
        schema_service=FakeSchemaService(),
        marketplace_id="MARKET1",
    ).build_plan(draft)

    assert plan["attributes"]["country_of_origin"] == [{"value": "MY"}]


def test_payload_builder_has_no_product_type_specific_cabinet_branch():
    source = Path(
        "src/services/amazon_listing_payload_builder.py"
    ).read_text(encoding="utf-8")

    assert "CABINET" not in source
    assert "normalize_cabinet_attributes" not in source


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

    plan = AmazonListingPayloadBuilder(
        schema_service=FakeSchemaService(),
    ).build_plan(draft)

    attrs = plan["attributes"]
    assert "main_product_image_locator" not in attrs
    assert "item_depth_width_height" not in attrs
    assert "purchasable_offer" not in attrs


def test_home_mirror_fabric_type_uses_material_when_available():
    product = _product()
    product.attributes.pop("Main Material", None)
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="HOME_MIRROR",
        standard_product=product,
        content=ListingContent(title="Wall Mirror"),
        offer=ListingOffer(price=99.99, quantity=5),
    )

    plan = AmazonListingPayloadBuilder(
        schema_service=FakeSchemaService(),
    ).build_plan(draft)

    assert plan["attributes"]["fabric_type"] == [{"value": "Glass, Metal"}]


def test_home_mirror_fabric_type_prefers_supplier_material():
    product = _product()
    product.attributes["Main Material"] = "Stainless Steel"
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="HOME_MIRROR",
        standard_product=product,
        content=ListingContent(title="Wall Mirror"),
        offer=ListingOffer(price=99.99, quantity=5),
    )

    plan = AmazonListingPayloadBuilder(
        schema_service=FakeSchemaService(),
    ).build_plan(draft)

    assert plan["attributes"]["fabric_type"] == [{"value": "Stainless Steel"}]


def test_home_mirror_schema_allowlist_removes_inapplicable_builder_attributes():
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="HOME_MIRROR",
        standard_product=_product(),
        content=ListingContent(title="Wall Mirror"),
        offer=ListingOffer(price=99.99, quantity=5),
    )

    attrs = AmazonListingPayloadBuilder(
        schema_service=HomeMirrorAllowlistSchemaService(),
    ).build_plan(draft)["attributes"]

    assert attrs["item_name"] == [{"value": "Wall Mirror"}]
    assert attrs["fabric_type"] == [{"value": "MDF"}]
    assert attrs["model_name"] == [{"value": "MPN1"}]
    assert attrs["frame"][0]["material"] == [
        {"value": "Metal", "language_tag": "en_US"}
    ]
    assert attrs["mounting_type"] == [{"value": "Wall Mount"}]
    assert attrs["is_assembly_required"] == [{"value": False}]
    assert attrs["item_shape"] == [{"value": "Rectangular"}]
    assert attrs["item_length_width"] == [
        {
            "length": {"value": 34.0, "unit": "inches"},
            "width": {"value": 30.0, "unit": "inches"},
        }
    ]
    assert attrs["included_components"] == [{"value": "Mirror"}]
    assert attrs["special_feature"] == [{"value": "Wall Mounted"}]
    assert attrs["room_type"] == [{"value": "Bathroom"}]
    assert attrs["number_of_items"] == [{"value": 1}]
    assert "item_depth" not in attrs
    assert "item_type_name" not in attrs
    assert "item_width" not in attrs
    assert "item_height" not in attrs
    assert "target_audience_base" not in attrs


def test_fabric_type_skipped_when_schema_does_not_require_it():
    product = _product()
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="SOME_OTHER_TYPE",
        standard_product=product,
        content=ListingContent(title="Generic Product"),
        offer=ListingOffer(price=10.0, quantity=1),
    )

    plan = AmazonListingPayloadBuilder(
        schema_service=FakeSchemaService(),
    ).build_plan(draft)

    assert "fabric_type" not in plan["attributes"]
