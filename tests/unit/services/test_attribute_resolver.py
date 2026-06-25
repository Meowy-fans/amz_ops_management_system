"""Unit tests for API attribute resolver."""

from src.models.amazon_listing import AmazonListingDraft, ListingContent, ListingOffer
from src.models.product import DimensionSpec, StandardProduct
from src.services.attribute_resolver import AttributeResolution, AttributeResolver
from src.services.llm_attribute_extractor import LLMAttributeExtraction
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.attribute_payload_renderer import AttributePayloadRenderer


class FakeSchemaService:
    def get_cached_valid_values(self, product_type, field_name):
        values = {
            "mounting_type": ["Freestanding", "Wall Mount"],
            "is_assembly_required": ["Yes", "No"],
        }
        return values.get(field_name)


class FakeLLMExtractor:
    def __init__(self, extraction):
        self.extraction = extraction
        self.calls = []

    def extract(self, draft, attribute, config, schema_service=None):
        self.calls.append((draft.sku, attribute, config))
        return self.extraction


def _draft():
    product = StandardProduct(
        sku="MEOW1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        attributes={
            "Mounting Type": "free standing",
            "Main Material": "MDF",
            "Number of Drawers": "2",
        },
        dimensions=DimensionSpec(assembled_length=30, assembled_width=20),
    )
    return AmazonListingDraft(
        sku="MEOW1",
        vendor_sku="GIGA1",
        product_type="CABINET",
        standard_product=product,
        content=ListingContent(
            title="Bathroom Cabinet",
            description="Cabinet with drawer storage",
        ),
        offer=ListingOffer(price=199.99, quantity=12),
    )


def test_resolver_uses_source_priority_and_enum_alignment():
    rules = {
        "product_type": "CABINET",
        "version": "test_rules",
        "attributes": {
            "mounting_type": {
                "level": "required",
                "shape": "value",
                "sources": [
                    {"path": "product.attributes.Mounting Type"},
                    {"default": "Freestanding", "confidence": "high"},
                ],
                "transform": "enum",
            }
        },
    }
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"CABINET": rules}),
        schema_service=FakeSchemaService(),
    )

    results = resolver.resolve(_draft())

    result = results["mounting_type"]
    assert result.value == "Freestanding"
    assert result.source == "product.attributes.Mounting Type"
    assert result.confidence == "high"
    assert result.state == "resolved_high_confidence"


def test_resolver_records_default_evidence_and_medium_confidence():
    rules = {
        "product_type": "CABINET",
        "attributes": {
            "is_assembly_required": {
                "level": "required",
                "shape": "value",
                "sources": [
                    {
                        "default": "Yes",
                        "confidence": "medium",
                        "evidence": "Supplier flat-pack furniture default",
                    }
                ],
                "transform": "enum",
            }
        },
    }
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"CABINET": rules}),
        schema_service=FakeSchemaService(),
    )

    result = resolver.resolve(_draft())["is_assembly_required"]

    assert result.value == "Yes"
    assert result.source == "default"
    assert result.confidence == "medium"
    assert result.evidence == "Supplier flat-pack furniture default"
    assert result.state == "resolved_with_default"


def test_renderer_outputs_amazon_attribute_shapes():
    rules = {
        "product_type": "CABINET",
        "attributes": {
            "number_of_drawers": {
                "level": "recommended",
                "shape": "value",
                "sources": [{"path": "product.attributes.Number of Drawers"}],
                "transform": "integer",
            },
            "included_components": {
                "level": "recommended",
                "shape": "list_value",
                "sources": [{"default": "Cabinet", "confidence": "high"}],
                "transform": "text",
            },
        },
    }
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"CABINET": rules}),
    )
    resolved = resolver.resolve(_draft())

    attrs = AttributePayloadRenderer().render(resolved)

    assert attrs["number_of_drawers"] == [{"value": 2}]
    assert attrs["included_components"] == [{"value": "Cabinet"}]


def test_required_low_confidence_result_is_blocking():
    rules = {
        "product_type": "CABINET",
        "attributes": {
            "special_feature": {
                "level": "required",
                "shape": "list_value",
                "sources": [{"default": "Storage", "confidence": "low"}],
                "transform": "text",
            }
        },
    }
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"CABINET": rules}),
    )

    result = resolver.resolve(_draft())["special_feature"]

    assert result.confidence == "low"
    assert result.blocking is True
    assert result.state == "resolved_low_confidence"


def test_resolver_uses_llm_source_before_default_with_medium_confidence_cap():
    rules = {
        "product_type": "CABINET",
        "attributes": {
            "room_type": {
                "level": "recommended",
                "shape": "list_value",
                "sources": [
                    {"path": "product.attributes.Room Type"},
                    {"llm": {"hint": "Extract room placement from product text"}},
                    {"default": "Living Room", "confidence": "medium"},
                ],
                "transform": "text",
            }
        },
    }
    extractor = FakeLLMExtractor(
        LLMAttributeExtraction(
            value="Bathroom",
            evidence="A modern cabinet for bathrooms.",
            confidence="high",
        )
    )
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"CABINET": rules}),
        llm_extractor=extractor,
    )

    result = resolver.resolve(_draft())["room_type"]

    assert result.value == "Bathroom"
    assert result.source == "llm"
    assert result.evidence == "A modern cabinet for bathrooms."
    assert result.confidence == "medium"
    assert result.state == "resolved_high_confidence"
    assert extractor.calls[0][1] == "room_type"


def test_required_llm_resolution_needs_review_without_hard_blocking():
    rules = {
        "product_type": "HOME_MIRROR",
        "attributes": {
            "mounting_type": {
                "level": "required",
                "shape": "list_value",
                "sources": [
                    {"llm": {"hint": "Extract mounting type", "enum_locked": True}},
                ],
                "transform": "text",
            }
        },
    }
    extractor = FakeLLMExtractor(
        LLMAttributeExtraction(
            value="Wall Mounted",
            evidence="Wall mounted rectangular mirror",
            confidence="medium",
        )
    )
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"HOME_MIRROR": rules}),
        llm_extractor=extractor,
    )
    draft = _draft()
    draft.product_type = "HOME_MIRROR"

    result = resolver.resolve(draft)["mounting_type"]

    assert result.value == "Wall Mounted"
    assert result.source == "llm"
    assert result.confidence == "medium"
    assert result.state == "needs_manual_review"
    assert result.review_status == "pending"
    assert result.review_route == "human"
    assert result.blocking is False


def test_required_llm_resolution_can_be_auto_approved_by_confidence_scorer():
    rules = {
        "product_type": "CHAIR",
        "attributes": {
            "included_components": {
                "level": "required",
                "shape": "list_value",
                "sources": [{"llm": {"hint": "Extract included components"}}],
                "transform": "text",
            }
        },
    }
    extractor = FakeLLMExtractor(
        LLMAttributeExtraction(
            value="Chair",
            evidence="Cabinet with drawer storage",
            confidence="medium",
        )
    )
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"CHAIR": rules}),
        llm_extractor=extractor,
    )
    draft = _draft()
    draft.product_type = "CHAIR"

    result = resolver.resolve(draft)["included_components"]

    assert result.state == "auto_approved"
    assert result.review_status == "auto_approved"
    assert result.review_route == "auto_approved"
    assert result.confidence_score == 65
    assert result.blocking is False


def test_required_llm_null_falls_through_to_safe_default():
    rules = {
        "product_type": "HOME_MIRROR",
        "attributes": {
            "number_of_items": {
                "level": "required",
                "shape": "list_value",
                "sources": [
                    {"llm": {"hint": "Extract item count"}},
                    {
                        "default": 1,
                        "confidence": "medium",
                        "evidence": "Single item fallback.",
                        "safe_default": True,
                    },
                ],
                "transform": "integer",
            }
        },
    }
    extractor = FakeLLMExtractor(
        LLMAttributeExtraction(value=None, warnings=["not_found"])
    )
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"HOME_MIRROR": rules}),
        llm_extractor=extractor,
    )
    draft = _draft()
    draft.product_type = "HOME_MIRROR"

    result = resolver.resolve(draft)["number_of_items"]

    assert result.value == 1
    assert result.source == "default"
    assert result.state == "resolved_with_default"
    assert result.blocking is False
    assert result.safe_default is True
    assert result.as_dict()["safe_default"] is True


def test_resolver_override_skips_source_chain_and_keeps_review_completed():
    rules = {
        "product_type": "CHAIR",
        "attributes": {
            "included_components": {
                "level": "required",
                "shape": "list_value",
                "sources": [{"llm": {"hint": "Extract included components"}}],
                "transform": "text",
            }
        },
    }
    extractor = FakeLLMExtractor(
        LLMAttributeExtraction(value="ShouldNotBeUsed", evidence="x", confidence="medium")
    )
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"CHAIR": rules}),
        llm_extractor=extractor,
    )
    draft = _draft()
    draft.product_type = "CHAIR"

    result = resolver.resolve(
        draft,
        overrides={"included_components": {"value": "Chair", "evidence": "Reviewed"}},
    )["included_components"]

    assert result.value == "Chair"
    assert result.source == "review_override"
    assert result.state == "review_completed"
    assert result.review_status == "completed"
    assert result.blocking is False
    assert extractor.calls == []


def test_resolver_supports_boolean_and_passthrough_transforms():
    rules = {
        "product_type": "HOME_MIRROR",
        "attributes": {
            "is_assembly_required": {
                "level": "required",
                "shape": "list_value",
                "sources": [{"default": False, "confidence": "medium", "evidence": "No assembly"}],
                "transform": "boolean",
            },
            "frame": {
                "level": "required",
                "shape": "object",
                "sources": [
                    {
                        "default": {"material": [{"value": "Metal"}]},
                        "confidence": "medium",
                        "evidence": "Frame fallback",
                    }
                ],
                "transform": "passthrough",
            },
        },
    }
    draft = _draft()
    draft.product_type = "HOME_MIRROR"
    resolver = AttributeResolver(
        rule_loader=AttributeRuleLoader(config_by_type={"HOME_MIRROR": rules}),
    )

    results = resolver.resolve(draft)

    assert results["is_assembly_required"].value is False
    assert results["frame"].value == {"material": [{"value": "Metal"}]}


def test_renderer_supports_measure_and_object_shapes_with_schema_allowlist():
    resolutions = {
        "item_width": AttributeResolution(
            attribute="item_width",
            value={"value": 24, "unit": "inches"},
            shape="measure",
            confidence="high",
            state="resolved_high_confidence",
        ),
        "frame": AttributeResolution(
            attribute="frame",
            value={"material": [{"value": "Metal"}]},
            shape="object",
            confidence="high",
            state="resolved_high_confidence",
        ),
        "item_type_name": AttributeResolution(
            attribute="item_type_name",
            value="Mirror",
            shape="value",
            confidence="high",
            state="resolved_high_confidence",
        ),
    }

    attrs = AttributePayloadRenderer().render(
        resolutions,
        allowed_attributes={"item_width", "frame"},
    )

    assert attrs == {
        "item_width": [{"value": 24, "unit": "inches"}],
        "frame": [{"material": [{"value": "Metal"}]}],
    }
