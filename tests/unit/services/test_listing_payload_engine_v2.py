"""Tests for V2 read-only payload engine orchestration."""

from src.models.amazon_listing import (
    AmazonListingDraft,
    ListingContent,
    ListingOffer,
    ListingVariation,
)
from src.models.product import DimensionSpec, StandardProduct
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.llm_attribute_extractor import LLMAttributeExtraction
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
from src.services.review_adapter_v2 import ReviewAdapterV2


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
                "required": ["item_name", "frame"],
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


class FakeLLMExtractor:
    def extract(self, draft, requirement):
        assert draft.sku == "SKU1"
        assert requirement.path_key in {"frame.color", "frame.color.value"}
        return LLMAttributeExtraction(
            value="Black",
            evidence="Black Chair",
            confidence="medium",
        )


class FakeConfidenceScorer:
    def score_tree(self, resolution_root, draft, requirement_root):
        for node in _walk_resolutions(resolution_root):
            if node.source == "llm" and not node.children:
                node.confidence_score = 45
                node.review_route = "ai_agent"
            else:
                node.confidence_score = 100
                node.review_route = "auto_approved"


class FakeSofaDraftBuilder:
    def build(self, product_data, product_type):
        assert product_type == "SOFA"
        product = StandardProduct(
            sku="SKU1",
            vendor_sku="GIGA1",
            vendor_source="giga",
            attributes={
                "Main Material": "Velvet",
                "Filler": "Foam",
            },
            dimensions=DimensionSpec(
                assembled_length=73.2,
                assembled_width=33.1,
                assembled_height=36,
            ),
        )
        return AmazonListingDraft(
            sku="SKU1",
            vendor_sku="GIGA1",
            product_type=product_type,
            standard_product=product,
            content=ListingContent(title="Queen Pull-Out Sofa Bed"),
            offer=ListingOffer(price=399.99, quantity=1),
        )


class FakeSofaSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "SOFA"
        return {
            "required_properties": ["seat"],
            "schema_json": {
                "required": ["seat"],
                "properties": {
                    "seat": {
                        "items": {
                            "required": [
                                "depth",
                                "height",
                                "interior_width",
                                "fill_material",
                                "material_type",
                            ],
                            "properties": {
                                "depth": _measure_schema(),
                                "height": _measure_schema(),
                                "interior_width": _measure_schema(),
                                "fill_material": _list_value_schema(),
                                "material_type": _list_value_schema(),
                            },
                        }
                    }
                }
            },
        }


class FakeOptionalCandidateSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "CHAIR"
        return {
            "required_properties": ["item_name"],
            "schema_json": {
                "required": ["item_name"],
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
                    "main_product_image_locator": {
                        "items": {
                            "required": ["media_location"],
                            "properties": {
                                "media_location": {"type": "string"},
                            },
                        }
                    },
                    "purchasable_offer": {"items": {"properties": {}}},
                    "fulfillment_availability": {"items": {"properties": {}}},
                    "variation_theme": {"items": {"properties": {"name": {}}}},
                    "not_in_candidate": {"items": {"properties": {}}},
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


def test_engine_routes_required_llm_leaf_to_pending_review():
    engine = ListingPayloadEngineV2(
        db=object(),
        schema_service=FakeSchemaService(),
        product_repo=FakeProductRepo(),
        draft_builder=FakeDraftBuilder(),
        llm_extractor=FakeLLMExtractor(),
        confidence_scorer=FakeConfidenceScorer(),
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
                        "sources": [{"llm": {"hint": "infer frame color"}}],
                    }
                }
            },
        },
    }

    plan = engine.build_read_only_plan("CHAIR", "SKU1", rules)
    pending_node = _find_resolution(plan.resolution_tree, "frame.color.value")
    review_items = ReviewAdapterV2()._extract_pending_paths(plan.resolution_tree)

    assert plan.attributes["frame"] == [
        {"color": [{"language_tag": "en_US", "value": "Black"}]}
    ]
    assert pending_node.source == "llm"
    assert pending_node.review_status == "pending"
    assert pending_node.review_route == "ai_agent"
    assert pending_node.blocking is True
    assert "NEEDS_REVIEW_REQUIRED_ATTRIBUTE" in pending_node.blocking_codes
    assert plan.pending_review_paths == ["frame.color.value"]
    assert plan.findings == [
        {
            "code": "NEEDS_REVIEW_REQUIRED_ATTRIBUTE",
            "path_key": "frame.color.value",
            "severity": "ERROR",
            "blocking": True,
            "message": "Required path needs review approval",
        }
    ]
    assert [item["path_key"] for item in review_items] == ["frame.color.value"]


def test_engine_candidate_attributes_include_deterministic_physical_fields():
    engine = ListingPayloadEngineV2(
        db=object(),
        schema_service=FakeSchemaService(),
        product_repo=FakeProductRepo(),
        draft_builder=FakeDraftBuilder(),
    )
    product = StandardProduct(
        sku="SKU1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        attributes={"color": "walnut", "material": "MDF", "mpn": "MPN-1"},
        dimensions=DimensionSpec(
            assembled_length=30,
            assembled_width=18,
            assembled_height=16,
            assembled_weight=99.74,
        ),
    )
    draft = AmazonListingDraft(
        sku="SKU1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        standard_product=product,
        content=ListingContent(title="Cabinet"),
        offer=ListingOffer(price=199.99, quantity=5),
    )

    attrs = engine._candidate_attributes_from_draft(
        draft,
        {
            "dimension_strategy": "item_depth_width_height",
            "additional_dimension_measures": ["item_width"],
        },
    )

    assert attrs["color"] == [{"value": "walnut"}]
    assert attrs["material"] == [{"value": "MDF"}]
    assert attrs["part_number"] == [{"value": "MPN-1"}]
    assert attrs["model_number"] == [{"value": "MPN-1"}]
    assert attrs["item_depth_width_height"] == [
        {
            "depth": {"value": 18.0, "unit": "inches"},
            "width": {"value": 30.0, "unit": "inches"},
            "height": {"value": 16.0, "unit": "inches"},
        }
    ]
    assert attrs["item_weight"] == [{"value": 99.74, "unit": "pounds"}]
    assert attrs["item_width"] == [{"value": 30.0, "unit": "inches"}]


def test_engine_candidate_attributes_preserve_images_and_variation_context():
    engine = ListingPayloadEngineV2(
        db=object(),
        schema_service=FakeSchemaService(),
        product_repo=FakeProductRepo(),
        draft_builder=FakeDraftBuilder(),
    )
    product = StandardProduct(
        sku="SKU1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        attributes={"color": "Black"},
        images=["https://example.test/main.jpg", "https://example.test/side.jpg"],
    )
    draft = AmazonListingDraft(
        sku="SKU1",
        vendor_sku="GIGA1",
        product_type="CHAIR",
        standard_product=product,
        content=ListingContent(title="Black Chair"),
        offer=ListingOffer(price=199.99, quantity=3),
        variation=ListingVariation(
            parentage_level="child",
            parent_sku="PARENT-1",
            variation_theme="Color",
            child_relationship_type="Variation",
            theme_attributes={"color_name": "Black"},
        ),
    )

    attrs = engine._candidate_attributes_from_draft(draft, {})

    assert attrs["main_product_image_locator"] == [
        {"media_location": "https://example.test/main.jpg"}
    ]
    assert attrs["other_product_image_locator_1"] == [
        {"media_location": "https://example.test/side.jpg"}
    ]
    assert attrs["parentage_level"] == [{"value": "child"}]
    assert attrs["variation_theme"] == [{"name": "COLOR"}]
    assert attrs["child_parent_sku_relationship"] == [
        {"parent_sku": "PARENT-1", "child_relationship_type": "Variation"}
    ]
    assert attrs["color"] == [{"value": "Black"}]


def test_engine_merges_schema_allowed_deterministic_candidate_attributes():
    engine = ListingPayloadEngineV2(
        db=object(),
        schema_service=FakeOptionalCandidateSchemaService(),
        product_repo=FakeProductRepo(),
        draft_builder=FakeDraftBuilder(),
    )
    product = StandardProduct(
        sku="SKU1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        attributes={},
        images=["https://example.test/main.jpg"],
    )
    draft = AmazonListingDraft(
        sku="SKU1",
        vendor_sku="GIGA1",
        product_type="CHAIR",
        standard_product=product,
        content=ListingContent(title="Black Chair"),
        offer=ListingOffer(price=199.99, quantity=3),
        variation=ListingVariation(
            parentage_level="parent",
            variation_theme="Color",
        ),
    )
    rules = {
        "attributes": {
            "item_name": {
                "sources": [{"path": "content.title"}],
            }
        }
    }

    plan = engine.build_read_only_plan_from_draft(draft, rules)

    assert plan.attributes["item_name"] == [
        {"language_tag": "en_US", "value": "Black Chair"}
    ]
    assert plan.attributes["main_product_image_locator"] == [
        {"media_location": "https://example.test/main.jpg"}
    ]
    assert plan.attributes["purchasable_offer"] == [
        {
            "currency": "USD",
            "marketplace_id": "ATVPDKIKX0DER",
            "our_price": [{"schedule": [{"value_with_tax": 199.99}]}],
        }
    ]
    assert plan.attributes["fulfillment_availability"] == [
        {"fulfillment_channel_code": "DEFAULT", "quantity": 3}
    ]
    assert plan.attributes["variation_theme"] == [{"name": "COLOR"}]
    assert "not_in_candidate" not in plan.attributes


def test_engine_renders_sofa_seat_required_children_from_rules():
    engine = ListingPayloadEngineV2(
        db=object(),
        schema_service=FakeSofaSchemaService(),
        product_repo=FakeProductRepo(),
        draft_builder=FakeSofaDraftBuilder(),
    )
    rules = AttributeRuleLoader().load("SOFA")

    plan = engine.build_read_only_plan("SOFA", "SKU1", rules)

    assert plan.missing_required_paths == []
    assert plan.findings == []
    assert plan.attributes["seat"] == [
        {
            "depth": {"value": 33.1, "unit": "inches"},
            "height": {"value": 36, "unit": "inches"},
            "interior_width": {"value": 73.2, "unit": "inches"},
            "fill_material": [{"language_tag": "en_US", "value": "Foam"}],
            "material_type": [{"language_tag": "en_US", "value": "Velvet"}],
        }
    ]


def test_engine_applies_cabinet_post_processors_and_universal_shape_parity():
    engine = ListingPayloadEngineV2(
        db=object(),
        schema_service=FakeCabinetDoorSchemaService(),
        product_repo=FakeProductRepo(),
        draft_builder=FakeDraftBuilder(),
    )
    rules = AttributeRuleLoader().load("CABINET")
    product = StandardProduct(
        sku="SKU1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        attributes={},
    )
    draft = AmazonListingDraft(
        sku="SKU1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        standard_product=product,
        content=ListingContent(title="Cabinet"),
        offer=ListingOffer(price=199.99, quantity=1),
    )

    plan = engine.build_read_only_plan_from_draft(draft, rules)

    assert plan.attributes["door"] == [
        {
            "style": [
                {
                    "value": "Shaker",
                    "language_tag": "en_US",
                    "marketplace_id": "ATVPDKIKX0DER",
                }
            ],
            "marketplace_id": "ATVPDKIKX0DER",
        }
    ]
    assert plan.attributes["externally_assigned_product_identifier"] == [
        {"type": "GTIN_EXEMPTION", "value": "product_does_not_have_gtin"}
    ]
    assert plan.attributes["supplier_declared_has_product_identifier_exemption"] == [
        {"value": "Yes"}
    ]


class FakeCabinetDoorSchemaService:
    def get_or_fetch_schema(self, product_type):
        return {
            "schema_json": {
                "required": ["door"],
                "properties": {
                    "door": {"type": "array"},
                    "externally_assigned_product_identifier": {"type": "array"},
                    "supplier_declared_has_product_identifier_exemption": {
                        "type": "array"
                    },
                    "item_name": {"type": "array"},
                },
            }
        }

    def get_expanded_required_properties(self, product_type):
        return ["door"]


def _walk_resolutions(node):
    yield node
    for child in node.children:
        yield from _walk_resolutions(child)


def _find_resolution(node, path_key):
    for candidate in _walk_resolutions(node):
        if candidate.path_key == path_key:
            return candidate
    raise AssertionError(f"resolution not found: {path_key}")


def _measure_schema():
    return {
        "items": {
            "required": ["unit", "value"],
            "properties": {
                "unit": {"type": "string"},
                "value": {"type": "number"},
            },
        }
    }


def _list_value_schema():
    return {
        "items": {
            "required": ["language_tag", "value"],
            "properties": {
                "language_tag": {"type": "string"},
                "value": {"type": "string"},
            },
        }
    }
