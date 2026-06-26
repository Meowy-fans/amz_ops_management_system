"""Unit tests for V2 path-level LLM attribute extraction."""

from src.models.amazon_listing import AmazonListingDraft, ListingContent
from src.models.product import StandardProduct
from src.services.llm_attribute_extractor_v2 import LLMAttributeExtractorV2
from src.services.requirement_models_v2 import RequirementNode


class FakeLLMClient:
    def __init__(self, response):
        self.response = response
        self.context = None

    def extract_attribute(self, context):
        self.context = context
        return self.response


def _draft():
    return AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CHAIR",
        standard_product=StandardProduct(
            sku="MEOW1",
            vendor_sku="GIGA1",
            vendor_source="giga",
            attributes={"Main Material": "Wood"},
            raw_source_data={
                "name": "Supplier Wooden Chair",
                "description": "Supplier raw description",
                "characteristics": ["Raw frame fact", "Raw seat fact"],
            },
        ),
        content=ListingContent(
            title="Wooden Dining Chair",
            bullets=["Solid oak frame with black finish"],
            description="A wooden chair with matte black frame and linen seat.",
        ),
    )


def _node(path_key, shape="list_value", enum_values=None, unit_values=None):
    return RequirementNode(
        path_key=path_key,
        schema_path=f"$.properties.{path_key}",
        name=path_key.split(".")[-1],
        shape=shape,
        enum_values=enum_values or [],
        unit_values=unit_values or [],
    )


def test_extract_returns_value_with_evidence_for_plain_path():
    client = FakeLLMClient(
        {"value": "black", "evidence": "matte black frame", "confidence": "medium"}
    )
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node("frame.color")

    result = extractor.extract(_draft(), requirement)

    assert result.value == "black"
    assert result.evidence == "matte black frame"
    assert result.confidence == "medium"
    assert result.warnings == []
    assert client.context is not None
    assert client.context["path_key"] == "frame.color"
    assert client.context["shape"] == "list_value"


def test_extract_enum_locked_canonicalizes_value():
    client = FakeLLMClient(
        {"value": "New_New", "evidence": "brand new chair", "confidence": "medium"}
    )
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node(
        "condition_type.value",
        shape="scalar",
        enum_values=["new_new", "used_good", "used_like_new"],
    )

    result = extractor.extract(_draft(), requirement)

    assert result.value == "new_new"
    assert result.warnings == []
    assert client.context["enum_locked"] is True
    assert "new_new" in client.context["valid_values"]


def test_extract_enum_locked_rejects_invalid_enum_value():
    client = FakeLLMClient(
        {"value": "brand_new", "evidence": "brand new", "confidence": "medium"}
    )
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node(
        "condition_type.value",
        shape="scalar",
        enum_values=["new_new", "used_good"],
    )

    result = extractor.extract(_draft(), requirement)

    assert result.value is None
    assert "invalid_enum" in result.warnings


def test_extract_missing_evidence_returns_null_with_warning():
    client = FakeLLMClient({"value": "black", "evidence": "", "confidence": "medium"})
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node("frame.color")

    result = extractor.extract(_draft(), requirement)

    assert result.value is None
    assert "missing_evidence" in result.warnings


def test_extract_value_not_found_returns_null():
    client = FakeLLMClient({"value": None, "evidence": "", "confidence": "low"})
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node("frame.material")

    result = extractor.extract(_draft(), requirement)

    assert result.value is None
    assert "not_found" in result.warnings


def test_extract_sensitive_path_returns_warning_without_llm_call():
    client = FakeLLMClient({"value": "Some Brand", "evidence": "Brand text"})
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node("brand.value", shape="scalar")

    result = extractor.extract(_draft(), requirement)

    assert result.value is None
    assert "sensitive" in result.warnings
    assert client.context is None


def test_extract_llm_unavailable_returns_warning():
    extractor = LLMAttributeExtractorV2(llm_client=None)
    requirement = _node("frame.color")

    result = extractor.extract(_draft(), requirement)

    assert result.value is None
    assert "llm_unavailable" in result.warnings


def test_extract_measure_unit_enum_locked():
    client = FakeLLMClient(
        {"value": "inches", "evidence": "dimensions in inches", "confidence": "medium"}
    )
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node(
        "item_depth_width_height.depth.unit",
        shape="scalar",
        enum_values=["inches"],
    )

    result = extractor.extract(_draft(), requirement)

    assert result.value == "inches"
    assert result.warnings == []


def test_extract_measure_unit_rejects_invalid_value():
    client = FakeLLMClient(
        {"value": "cm", "evidence": "dimensions in cm", "confidence": "medium"}
    )
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node(
        "item_depth_width_height.depth.unit",
        shape="scalar",
        enum_values=["inches"],
    )

    result = extractor.extract(_draft(), requirement)

    assert result.value is None
    assert "invalid_enum" in result.warnings


def test_extract_caps_confidence_to_medium():
    client = FakeLLMClient(
        {"value": "black", "evidence": "black frame", "confidence": "high"}
    )
    extractor = LLMAttributeExtractorV2(llm_client=client)
    requirement = _node("frame.color")

    result = extractor.extract(_draft(), requirement)

    assert result.confidence == "medium"
