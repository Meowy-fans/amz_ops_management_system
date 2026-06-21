"""Unit tests for constrained LLM attribute extraction."""

from src.models.amazon_listing import AmazonListingDraft, ListingContent
from src.models.product import StandardProduct
from src.services.llm_attribute_extractor import LLMAttributeExtractor


class FakeSchemaService:
    def get_cached_valid_values(self, product_type, field_name):
        values = {
            "mounting_type": ["Wall Mounted", "Freestanding"],
        }
        return values.get(field_name)


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
        product_type="HOME_MIRROR",
        standard_product=StandardProduct(
            sku="MEOW1",
            vendor_sku="GIGA1",
            vendor_source="giga",
            attributes={"Main Material": "Metal"},
        ),
        content=ListingContent(
            title="Wall Mirror",
            bullets=["Wall mounted rectangular mirror"],
            description="A metal framed mirror for bathroom walls.",
        ),
    )


def test_extractor_rejects_sensitive_attributes_before_llm_call():
    client = FakeLLMClient({"value": "Some Brand", "evidence": "Brand text"})
    extractor = LLMAttributeExtractor(llm_client=client)

    result = extractor.extract(_draft(), "brand", {"hint": "extract brand"})

    assert result.value is None
    assert result.confidence == "low"
    assert "sensitive" in result.warnings
    assert client.context is None


def test_extractor_requires_evidence_and_enum_lock():
    no_evidence = LLMAttributeExtractor(
        llm_client=FakeLLMClient({"value": "Wall Mounted", "evidence": ""})
    )

    missing = no_evidence.extract(
        _draft(),
        "mounting_type",
        {"hint": "extract mounting type", "enum_locked": True},
        schema_service=FakeSchemaService(),
    )

    assert missing.value is None
    assert "missing_evidence" in missing.warnings

    invalid_enum = LLMAttributeExtractor(
        llm_client=FakeLLMClient({"value": "Ceiling Hung", "evidence": "mounted"})
    )

    rejected = invalid_enum.extract(
        _draft(),
        "mounting_type",
        {"hint": "extract mounting type", "enum_locked": True},
        schema_service=FakeSchemaService(),
    )

    assert rejected.value is None
    assert "invalid_enum" in rejected.warnings


def test_extractor_caps_confidence_at_medium():
    client = FakeLLMClient({"value": "Wall Mounted", "evidence": "Wall mounted"})
    extractor = LLMAttributeExtractor(llm_client=client)

    result = extractor.extract(
        _draft(),
        "mounting_type",
        {"hint": "extract mounting type", "enum_locked": True},
        schema_service=FakeSchemaService(),
    )

    assert result.value == "Wall Mounted"
    assert result.confidence == "medium"
    assert result.evidence == "Wall mounted"
    assert client.context["attribute"] == "mounting_type"


def test_extractor_default_client_is_disabled_without_env(monkeypatch):
    monkeypatch.delenv("ATTRIBUTE_LLM_EXTRACTION_ENABLED", raising=False)
    extractor = LLMAttributeExtractor()

    result = extractor.extract(
        _draft(),
        "mounting_type",
        {"hint": "extract mounting type"},
        schema_service=FakeSchemaService(),
    )

    assert result.value is None
    assert "llm_unavailable" in result.warnings


def test_extractor_uses_default_client_when_enabled(monkeypatch):
    class Client:
        def extract_attribute(self, context):
            return {
                "value": "Wall Mounted",
                "evidence": "Wall mounted rectangular mirror",
                "confidence": "medium",
            }

    monkeypatch.setenv("ATTRIBUTE_LLM_EXTRACTION_ENABLED", "true")
    monkeypatch.setattr(
        "src.services.attribute_extraction_llm_client.AttributeExtractionLLMClient",
        lambda: Client(),
    )
    extractor = LLMAttributeExtractor()

    result = extractor.extract(
        _draft(),
        "mounting_type",
        {"hint": "extract mounting type"},
        schema_service=FakeSchemaService(),
    )

    assert result.value == "Wall Mounted"
    assert result.evidence == "Wall mounted rectangular mirror"
