"""Unit tests for ProductContentGenerator."""
import json
from unittest.mock import MagicMock

from src.models.product import DimensionSpec, StandardProduct
from src.services.product_content_generator import (
    EnrichedProductContent,
    ProductContentGenerator,
)


class FakeLLMResponse:
    def __init__(self, content):
        self.content = content


class FakeLLMService:
    def __init__(self, response_text=None):
        self.response_text = response_text or json.dumps(_valid_response())
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return FakeLLMResponse(self.response_text)


def _valid_response():
    return {
        "title": "30 inch Wall-Mounted Bathroom Vanity with Ceramic Sink - White",
        "bullet_1": "Space-Saving Design: Wall-mounted at 30 inches wide, fits compact bathrooms while providing full storage",
        "bullet_2": "Premium Materials: 18mm plywood construction with moisture-resistant finish outlasts MDF alternatives",
        "bullet_3": "Soft-Close System: Undermount drawer slides with damping mechanism for silent, smooth operation",
        "bullet_4": "Easy Installation: Pre-assembled cabinet with detailed manual, mounts in under 2 hours",
        "bullet_5": "Quality Assurance: 1-year manufacturer warranty with responsive US-based support team",
        "description": "<b>Modern Bathroom Storage Solution</b><br/><br/>Your bathroom deserves both style and function. This 30-inch wall-mounted vanity solves the storage shortage in compact bathrooms.<br/><br/>Built from 18mm plywood with a moisture-resistant finish, this cabinet resists the warping and swelling common in humid environments.<br/><br/><b>Thoughtful Details</b>: Soft-close drawer slides prevent slamming. The ceramic integrated sink resists stains and scratches.<br/><br/>Backed by 1-year warranty and responsive support.",
        "search_terms": "bathroom vanity, wall mounted cabinet, ceramic sink vanity, floating bathroom cabinet, modern bathroom storage",
        "generic_keyword": "bathroom vanity cabinet",
    }


def _make_product():
    return StandardProduct(
        sku="MEOW-001",
        vendor_sku="GIGA-001",
        vendor_source="giga",
        name="30 inch Wall-Mounted Bathroom Vanity with Ceramic Sink - White",
        description="Premium bathroom vanity with ceramic sink.",
        bullet_points=["Space saving", "Premium materials", "Soft close"],
        images=["https://cdn.example/main.jpg"],
        category_hint="Bathroom Vanities",
        attributes={
            "Main Color": "White",
            "Main Material": "Plywood + Ceramic",
            "Product Style": "Modern",
        },
        dimensions=DimensionSpec(
            assembled_length=30.0,
            assembled_width=18.5,
            assembled_height=34.4,
            assembled_weight=101.4,
        ),
    )


# ── basic generation ──────────────────────────────────────────────

def test_generate_returns_enriched_content():
    llm = FakeLLMService()
    gen = ProductContentGenerator(llm_service=llm)
    product = _make_product()

    result = gen.generate(product, product_type="CABINET")

    assert isinstance(result, EnrichedProductContent)
    assert "30 inch" in result.title
    assert len(result.bullet_1) > 0
    assert len(result.description) > 0
    assert len(result.search_terms) > 0
    assert len(result.generic_keyword) > 0


def test_generate_injects_category_in_prompt():
    llm = FakeLLMService()
    gen = ProductContentGenerator(llm_service=llm)
    product = _make_product()

    gen.generate(product, product_type="CABINET")

    user_prompt = llm.calls[0]["user_prompt"]
    assert "CABINET" in user_prompt
    assert "30 inch" in user_prompt


# ── validation ────────────────────────────────────────────────────

def test_validate_title_too_long():
    gen = ProductContentGenerator(llm_service=FakeLLMService())
    resp = _valid_response()
    resp["title"] = "X" * 250
    llm = FakeLLMService(json.dumps(resp))
    gen._llm = llm

    result = gen.generate(_make_product(), "CABINET")
    assert any("Title too long" in w for w in result.validation_warnings)


def test_validate_prohibited_words():
    gen = ProductContentGenerator(llm_service=FakeLLMService())
    resp = _valid_response()
    resp["title"] = "The Best Amazing Cabinet #1 Top-Rated"
    llm = FakeLLMService(json.dumps(resp))
    gen._llm = llm

    result = gen.generate(_make_product(), "CABINET")
    assert any("best" in w.lower() for w in result.validation_warnings)


def test_validate_all_caps_title():
    gen = ProductContentGenerator(llm_service=FakeLLMService())
    resp = _valid_response()
    resp["title"] = "PREMIUM BATHROOM VANITY CABINET"
    llm = FakeLLMService(json.dumps(resp))
    gen._llm = llm

    result = gen.generate(_make_product(), "CABINET")
    assert any("ALL CAPS" in w for w in result.validation_warnings)


def test_validate_unsafe_html():
    gen = ProductContentGenerator(llm_service=FakeLLMService())
    resp = _valid_response()
    resp["description"] = "<div>Bad tag</div> <b>Good</b>"
    llm = FakeLLMService(json.dumps(resp))
    gen._llm = llm

    result = gen.generate(_make_product(), "CABINET")
    assert any("Unsafe HTML" in w for w in result.validation_warnings)


def test_validate_no_warnings_for_clean_content():
    gen = ProductContentGenerator(llm_service=FakeLLMService())
    # Default fake response is clean
    result = gen.generate(_make_product(), "CABINET")
    assert result.validation_warnings == []


# ── error handling ────────────────────────────────────────────────

def test_llm_failure_returns_empty_content():
    class FailingLLM:
        def generate(self, **kwargs):
            raise RuntimeError("LLM down")

    gen = ProductContentGenerator(llm_service=FailingLLM())
    result = gen.generate(_make_product(), "CABINET")
    assert result.title == ""
    assert any("LLM call failed" in w for w in result.validation_warnings)


def test_malformed_json_returns_empty():
    gen = ProductContentGenerator(llm_service=FakeLLMService("not valid json {{{"))
    result = gen.generate(_make_product(), "CABINET")
    assert any("parse" in w.lower() for w in result.validation_warnings)
