"""Tests for V2 path-level evidence resolver."""

from src.models.amazon_listing import AmazonListingDraft, ListingContent, ListingOffer
from src.models.product import StandardProduct
from src.services.evidence_resolver_v2 import EvidenceResolverV2
from src.services.requirement_models_v2 import RequirementNode


def test_resolver_resolves_path_source_to_resolution_node():
    root = _root(
        RequirementNode(
            path_key="item_name",
            schema_path="$.properties.item_name",
            name="item_name",
            shape="list_value",
            required=True,
        )
    )
    rules = {
        "version": "rules_v1",
        "attributes": {
            "item_name": {
                "transform": "text",
                "sources": [{"path": "content.title", "confidence": "high"}],
            }
        },
    }

    result = EvidenceResolverV2().resolve(root, _draft(), rules)

    node = result.children[0]
    assert node.path_key == "item_name"
    assert node.value == "Walnut Dining Chair"
    assert node.source == "content.title"
    assert node.confidence == "high"
    assert node.blocking is False


def test_resolver_inherits_list_value_child_from_parent_resolution():
    root = _root(
        RequirementNode(
            path_key="item_name",
            schema_path="$.properties.item_name",
            name="item_name",
            shape="list_value",
            required=True,
            children=[
                RequirementNode(
                    path_key="item_name.value",
                    schema_path="$.properties.item_name.items.properties.value",
                    name="value",
                    shape="scalar",
                    required=True,
                )
            ],
        )
    )
    rules = {
        "attributes": {
            "item_name": {
                "sources": [{"path": "content.title", "confidence": "high"}],
            }
        }
    }

    node = EvidenceResolverV2().resolve(root, _draft(), rules).children[0]

    assert node.children[0].path_key == "item_name.value"
    assert node.children[0].value == "Walnut Dining Chair"
    assert node.children[0].source == "content.title"
    assert node.children[0].blocking is False


def test_resolver_inherits_scalar_list_child_from_parent_resolution():
    root = _root(
        RequirementNode(
            path_key="bullet_point",
            schema_path="$.properties.bullet_point",
            name="bullet_point",
            shape="array_object",
            required=True,
            children=[
                RequirementNode(
                    path_key="bullet_point.value",
                    schema_path="$.properties.bullet_point.items.properties.value",
                    name="value",
                    shape="scalar",
                    required=True,
                )
            ],
        )
    )
    rules = {
        "attributes": {
            "bullet_point": {
                "transform": "passthrough",
                "sources": [{"path": "content.bullets", "confidence": "high"}],
            }
        }
    }

    draft = _draft()
    draft.content.bullets = ["Sturdy frame", "Easy assembly"]

    node = EvidenceResolverV2().resolve(root, draft, rules).children[0]

    assert node.value == ["Sturdy frame", "Easy assembly"]
    assert node.children[0].value == ["Sturdy frame", "Easy assembly"]
    assert node.children[0].source == "content.bullets"
    assert node.children[0].blocking is False


def test_resolver_falls_back_to_candidate_attributes_when_rules_missing():
    root = _root(
        RequirementNode(
            path_key="condition_type",
            schema_path="$.properties.condition_type",
            name="condition_type",
            shape="array_object",
            required=True,
            children=[
                RequirementNode(
                    path_key="condition_type.value",
                    schema_path="$.properties.condition_type.items.properties.value",
                    name="value",
                    shape="scalar",
                    required=True,
                )
            ],
        )
    )

    node = EvidenceResolverV2().resolve(
        root,
        _draft(),
        {"attributes": {}},
        candidate_attributes={"condition_type": [{"value": "new_new"}]},
    ).children[0]

    assert node.value == [{"value": "new_new"}]
    assert node.source == "candidate_attributes.condition_type"
    assert node.confidence == "high"
    assert node.blocking is False
    assert node.children[0].value == ["new_new"]
    assert node.children[0].blocking is False


def test_resolver_inherits_list_dict_child_from_candidate_parent():
    root = _root(
        RequirementNode(
            path_key="fulfillment_availability",
            schema_path="$.properties.fulfillment_availability",
            name="fulfillment_availability",
            shape="array_object",
            required=True,
            children=[
                RequirementNode(
                    path_key="fulfillment_availability.fulfillment_channel_code",
                    schema_path="$.properties.fulfillment_availability.items.properties.fulfillment_channel_code",
                    name="fulfillment_channel_code",
                    shape="scalar",
                    required=True,
                ),
                RequirementNode(
                    path_key="fulfillment_availability.quantity",
                    schema_path="$.properties.fulfillment_availability.items.properties.quantity",
                    name="quantity",
                    shape="scalar",
                    required=True,
                ),
            ],
        )
    )

    node = EvidenceResolverV2().resolve(
        root,
        _draft(),
        {"attributes": {}},
        candidate_attributes={
            "fulfillment_availability": [
                {"fulfillment_channel_code": "DEFAULT", "quantity": 3}
            ]
        },
    ).children[0]

    assert [child.value for child in node.children] == [["DEFAULT"], [3]]
    assert all(child.blocking is False for child in node.children)


def test_resolver_aligns_enum_from_requirement_metadata():
    root = _root(
        RequirementNode(
            path_key="is_assembly_required",
            schema_path="$.properties.is_assembly_required",
            name="is_assembly_required",
            shape="list_value",
            required=True,
            enum_values=["Yes", "No"],
        )
    )
    rules = {
        "attributes": {
            "is_assembly_required": {
                "transform": "enum",
                "sources": [{"path": "product.attributes.Assembly Required"}],
            }
        }
    }

    node = EvidenceResolverV2().resolve(root, _draft(), rules).children[0]

    assert node.value == "Yes"


def test_resolver_records_safe_default_and_blocks_unsafe_required_default():
    root = _root(
        RequirementNode(
            path_key="number_of_items",
            schema_path="$.properties.number_of_items",
            name="number_of_items",
            shape="list_value",
            required=True,
        ),
        RequirementNode(
            path_key="item_shape",
            schema_path="$.properties.item_shape",
            name="item_shape",
            shape="list_value",
            required=True,
        ),
    )
    rules = {
        "attributes": {
            "number_of_items": {
                "transform": "integer",
                "sources": [
                    {
                        "default": 1,
                        "confidence": "medium",
                        "evidence": "Single item fallback",
                        "safe_default": True,
                    }
                ],
            },
            "item_shape": {
                "sources": [
                    {
                        "default": "Rectangular",
                        "confidence": "medium",
                        "evidence": "Generic fallback",
                    }
                ],
            },
        }
    }

    result = EvidenceResolverV2().resolve(root, _draft(), rules)

    number_of_items, item_shape = result.children
    assert number_of_items.value == 1
    assert number_of_items.source == "default"
    assert number_of_items.safe_default is True
    assert number_of_items.blocking is False
    assert item_shape.blocking is True
    assert item_shape.blocking_codes == ["UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE"]


def test_resolver_marks_required_path_missing_when_no_source_matches():
    root = _root(
        RequirementNode(
            path_key="frame_material",
            schema_path="$.properties.frame_material",
            name="frame_material",
            shape="list_value",
            required=True,
        )
    )
    rules = {
        "attributes": {
            "frame_material": {
                "sources": [{"path": "product.attributes.Frame Material"}],
            }
        }
    }

    node = EvidenceResolverV2().resolve(root, _draft(), rules).children[0]

    assert node.value is None
    assert node.blocking is True
    assert node.blocking_codes == ["MISSING_REQUIRED_ATTRIBUTE_RULE"]


def test_resolver_applies_review_override_by_path_key():
    root = _root(
        RequirementNode(
            path_key="frame.material",
            schema_path="$.properties.frame.items.properties.material",
            name="material",
            shape="list_value",
            required=True,
        )
    )
    overrides = {
        "frame.material": {
            "value": "Rubberwood",
            "evidence": "Human reviewed supplier spec",
            "confidence": "high",
        }
    }

    node = EvidenceResolverV2().resolve(root, _draft(), {}, overrides).children[0]

    assert node.value == "Rubberwood"
    assert node.source == "review_override"
    assert node.review_status == "completed"
    assert node.blocking is False


def test_resolver_prefers_child_override_over_inherited_parent_value():
    root = _root(
        RequirementNode(
            path_key="seating_capacity",
            schema_path="$.properties.seating_capacity",
            name="seating_capacity",
            shape="list_value",
            required=True,
            children=[
                RequirementNode(
                    path_key="seating_capacity.value",
                    schema_path="$.properties.seating_capacity.items.properties.value",
                    name="value",
                    shape="scalar",
                    required=True,
                )
            ],
        )
    )
    rules = {
        "attributes": {
            "seating_capacity": {
                "sources": [{"llm": {"hint": "extract seats"}}],
            }
        }
    }
    overrides = {
        "seating_capacity.value": {
            "value": 2,
            "evidence": "Seats: 2 Seat",
            "confidence": "medium",
            "review_status": "completed",
        }
    }

    parent = EvidenceResolverV2(
        llm_extractor=FakeLLMExtractor({"seating_capacity": 2})
    ).resolve(root, _draft(), rules, overrides)
    child = parent.children[0].children[0]

    assert child.path_key == "seating_capacity.value"
    assert child.value == 2
    assert child.source == "review_override"
    assert child.review_status == "completed"
    assert child.blocking is False


def test_resolver_resolves_child_rules_recursively():
    root = _root(
        RequirementNode(
            path_key="maximum_weight_recommendation",
            schema_path="$.properties.maximum_weight_recommendation",
            name="maximum_weight_recommendation",
            shape="measure",
            required=True,
            children=[
                RequirementNode(
                    path_key="maximum_weight_recommendation.value",
                    schema_path="$.properties.maximum_weight_recommendation.items.properties.value",
                    name="value",
                    shape="scalar",
                    required=True,
                ),
                RequirementNode(
                    path_key="maximum_weight_recommendation.unit",
                    schema_path="$.properties.maximum_weight_recommendation.items.properties.unit",
                    name="unit",
                    shape="scalar",
                    required=True,
                ),
            ],
        )
    )
    rules = {
        "attributes": {
            "maximum_weight_recommendation": {
                "children": {
                    "value": {
                        "transform": "integer",
                        "sources": [{"path": "product.attributes.Weight Capacity"}],
                    },
                    "unit": {
                        "sources": [{"default": "pounds", "safe_default": True}],
                    },
                }
            }
        }
    }

    node = EvidenceResolverV2().resolve(root, _draft(), rules).children[0]

    assert [child.value for child in node.children] == [250, "pounds"]
    assert all(child.blocking is False for child in node.children)


def test_resolver_resolves_yaml_only_children_for_structural_parent():
    root = _root(
        RequirementNode(
            path_key="frame",
            schema_path="$.properties.frame",
            name="frame",
            shape="array_object",
            required=True,
            children=[],
        )
    )
    rules = {
        "attributes": {
            "frame": {
                "children": {
                    "material": {
                        "shape": "list_value",
                        "children": {
                            "value": {
                                "sources": [
                                    {"path": "product.attributes.Main Material", "confidence": "high"}
                                ],
                            },
                        },
                    },
                }
            }
        }
    }
    draft = _draft()
    draft.standard_product.attributes["Main Material"] = "Rubber Wood"

    node = EvidenceResolverV2().resolve(root, draft, rules).children[0]

    assert node.path_key == "frame"
    assert len(node.children) == 1
    material = node.children[0]
    assert material.path_key == "frame.material"
    assert material.children[0].path_key == "frame.material.value"
    assert material.children[0].value == "Rubber Wood"
    assert material.children[0].blocking is False


def test_resolver_uses_llm_extractor_when_llm_source_configured():
    from src.services.llm_attribute_extractor import LLMAttributeExtraction

    class FakeExtractor:
        def __init__(self, extraction):
            self.extraction = extraction
            self.calls = []

        def extract(self, draft, requirement):
            self.calls.append(requirement.path_key)
            return self.extraction

    root = _root(
        RequirementNode(
            path_key="frame.color",
            schema_path="$.properties.frame.items.properties.color",
            name="color",
            shape="list_value",
            required=True,
        )
    )
    rules = {
        "attributes": {
            "frame.color": {
                "sources": [{"llm": True}],
            }
        }
    }
    extractor = FakeExtractor(
        LLMAttributeExtraction(
            value="black",
            evidence="matte black frame",
            confidence="medium",
        )
    )

    node = EvidenceResolverV2(llm_extractor=extractor).resolve(root, _draft(), rules).children[0]

    assert node.value == "black"
    assert node.source == "llm"
    assert node.confidence == "medium"
    assert node.evidence == "matte black frame"
    assert node.blocking is False
    assert extractor.calls == ["frame.color"]


def test_resolver_falls_back_to_next_source_when_llm_returns_null():
    from src.services.llm_attribute_extractor import LLMAttributeExtraction

    class FakeExtractor:
        def extract(self, draft, requirement):
            return LLMAttributeExtraction(value=None, warnings=["not_found"])

    root = _root(
        RequirementNode(
            path_key="frame.color",
            schema_path="$.properties.frame.items.properties.color",
            name="color",
            shape="list_value",
            required=True,
        )
    )
    rules = {
        "attributes": {
            "frame.color": {
                "sources": [
                    {"llm": True},
                    {"path": "content.title", "confidence": "high"},
                ]
            }
        }
    }

    node = EvidenceResolverV2(llm_extractor=FakeExtractor()).resolve(
        root, _draft(), rules
    ).children[0]

    assert node.value == "Walnut Dining Chair"
    assert node.source == "content.title"
    assert node.confidence == "high"


def test_resolver_defers_llm_when_no_extractor_configured():
    root = _root(
        RequirementNode(
            path_key="frame.color",
            schema_path="$.properties.frame.items.properties.color",
            name="color",
            shape="list_value",
            required=True,
        )
    )
    rules = {
        "attributes": {
            "frame.color": {
                "sources": [{"llm": True}],
            }
        }
    }

    node = EvidenceResolverV2().resolve(root, _draft(), rules).children[0]

    assert node.value is None
    assert node.source == ""
    assert node.confidence == "low"
    assert node.blocking is True
    assert "MISSING_REQUIRED_ATTRIBUTE_RULE" in node.blocking_codes


class FakeLLMExtractor:
    def __init__(self, values):
        self.values = values

    def extract(self, draft, requirement, **kwargs):
        value = self.values.get(requirement.path_key.split(".")[0])
        if value is None:
            return None
        return type(
            "Extraction",
            (),
            {
                "value": value,
                "evidence": f"llm:{value}",
                "confidence": "medium",
                "source_quote": f"llm:{value}",
            },
        )()


def _root(*children: RequirementNode) -> RequirementNode:
    return RequirementNode(
        path_key="CHAIR",
        schema_path="$",
        name="CHAIR",
        shape="root",
        required=True,
        children=list(children),
    )


def _draft() -> AmazonListingDraft:
    product = StandardProduct(
        sku="MEOW1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        attributes={
            "Assembly Required": "yes",
            "Weight Capacity": "250",
        },
    )
    return AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CHAIR",
        standard_product=product,
        content=ListingContent(title="Walnut Dining Chair"),
        offer=ListingOffer(price=99.99, quantity=3),
    )


def test_resolver_text_join_uses_bullets_for_product_description():
    root = _root(
        RequirementNode(
            path_key="product_description",
            schema_path="$.properties.product_description",
            name="product_description",
            shape="list_value",
            required=True,
        )
    )
    rules = {
        "version": "test",
        "attributes": {
            "product_description": {
                "transform": "text_join",
                "sources": [
                    {"path": "content.description"},
                    {"path": "content.bullets", "confidence": "high"},
                ],
            }
        },
    }
    draft = _draft()
    draft.content.description = ""
    draft.content.bullets = ["Soft fabric", "Easy assembly"]

    node = EvidenceResolverV2().resolve(root, draft, rules).children[0]

    assert node.value == "Soft fabric\nEasy assembly"
    assert node.source == "content.bullets"
    assert node.blocking is False


def test_resolver_enum_scan_and_integer_sources_for_sofa_paths():
    root = _root(
        RequirementNode(
            path_key="seating_capacity",
            schema_path="$.properties.seating_capacity",
            name="seating_capacity",
            shape="value",
            required=True,
            children=[
                RequirementNode(
                    path_key="seating_capacity.value",
                    schema_path="$.properties.seating_capacity.items.properties.value",
                    name="value",
                    shape="value",
                    required=True,
                )
            ],
        ),
        RequirementNode(
            path_key="sofa_type",
            schema_path="$.properties.sofa_type",
            name="sofa_type",
            shape="list_value",
            required=True,
            enum_values=[
                "sectional",
                "sleeper",
                "standard",
            ],
            children=[
                RequirementNode(
                    path_key="sofa_type.value",
                    schema_path="$.properties.sofa_type.items.properties.value",
                    name="value",
                    shape="value",
                    required=True,
                )
            ],
        ),
    )
    rules = {
        "version": "test",
        "attributes": {
            "seating_capacity": {
                "transform": "integer",
                "sources": [{"path": "product.attributes.Seats", "confidence": "high"}],
            },
            "sofa_type": {
                "transform": "enum_scan",
                "sources": [{"path": "content.title", "confidence": "high"}],
            },
        },
    }
    product = StandardProduct(
        sku="MEOW1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        name="Sectional Sofa",
        attributes={"Seats": "4 Seat"},
    )
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="SOFA",
        standard_product=product,
        content=ListingContent(
            title="Blue Curved Modular Sectional Sleeper Couch",
            bullets=[],
            description="",
        ),
        offer=ListingOffer(price=99.99, quantity=3),
    )

    result = EvidenceResolverV2().resolve(root, draft, rules)
    seating_capacity, sofa_type = result.children

    assert seating_capacity.children[0].value == 4
    assert sofa_type.children[0].value == "sectional"


def test_resolver_preserves_boolean_false_for_enum_transform():
    root = _root(
        RequirementNode(
            path_key="is_assembly_required",
            schema_path="$.properties.is_assembly_required",
            name="is_assembly_required",
            shape="array_object",
            required=True,
            children=[
                RequirementNode(
                    path_key="is_assembly_required.value",
                    schema_path="$.properties.is_assembly_required.items.properties.value",
                    name="value",
                    shape="value",
                    required=True,
                    enum_values=["False", "True"],
                )
            ],
        )
    )
    rules = {
        "version": "rules_v1",
        "attributes": {
            "is_assembly_required": {
                "children": {
                    "value": {
                        "transform": "enum",
                        "sources": [
                            {"path": "product.requires_assembly", "confidence": "high"},
                        ],
                    }
                }
            }
        },
    }
    product = StandardProduct(
        sku="MEOW1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        name="Bed Frame",
        requires_assembly=False,
    )
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="BED_FRAME",
        standard_product=product,
        content=ListingContent(title="Bed", bullets=[], description=""),
        offer=ListingOffer(price=100.0, quantity=1, currency="USD", condition_type="new_new"),
    )
    result = EvidenceResolverV2().resolve(root, draft, rules)
    value = result.children[0].children[0]
    assert value.value == "False"
    assert value.blocking is False


def test_resolver_normalizes_country_of_origin_names_to_iso_codes():
    root = _root(
        RequirementNode(
            path_key="country_of_origin",
            schema_path="$.properties.country_of_origin",
            name="country_of_origin",
            shape="list_value",
            required=True,
            enum_values=["CN", "MY", "VN", "US"],
            children=[
                RequirementNode(
                    path_key="country_of_origin.value",
                    schema_path="$.properties.country_of_origin.items.properties.value",
                    name="value",
                    shape="value",
                    required=True,
                    enum_values=["CN", "MY", "VN", "US"],
                )
            ],
        )
    )
    rules = {
        "version": "rules_v1",
        "attributes": {
            "country_of_origin": {
                "transform": "enum",
                "sources": [{"path": "product.attributes.place_of_origin", "confidence": "high"}],
            }
        },
    }
    product = StandardProduct(
        sku="MEOW1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        name="Table",
        attributes={"place_of_origin": "VIET NAM"},
    )
    draft = AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="TABLE",
        standard_product=product,
        content=ListingContent(title="Table", bullets=[], description=""),
        offer=ListingOffer(price=99.99, quantity=3),
    )

    result = EvidenceResolverV2().resolve(root, draft, rules)
    node = result.children[0]

    assert node.value == "VN"

