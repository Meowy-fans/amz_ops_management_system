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
