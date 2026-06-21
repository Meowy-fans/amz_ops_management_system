"""Compliance-focused tests for ProductContentGenerator."""
import json
import os

os.environ.setdefault("DATABASE_HOST", "test")
os.environ.setdefault("DATABASE_NAME", "test")
os.environ.setdefault("DATABASE_USER", "test")
os.environ.setdefault("DATABASE_PASSWORD", "test")

from src.models.product import StandardProduct
from src.services.product_content_generator import ProductContentGenerator


class FakeLLMResponse:
    def __init__(self, content):
        self.content = content


class SequenceLLMService:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        if not self.responses:
            raise RuntimeError("no responses left")
        return FakeLLMResponse(self.responses.pop(0))


class PassReviewer:
    def review(self, product, product_type, content):
        class Result:
            verdict = "pass"
            revision_instructions = ""
            issues = []

            def as_dict(self):
                return {"verdict": "pass", "issues": []}

        return Result()


def _product():
    return StandardProduct(
        sku="MEOW-001",
        vendor_sku="GIGA-001",
        vendor_source="giga",
        name="Bathroom Vanity",
        description="Moisture-resistant cabinet with bacteria-proof ceramic sink.",
    )


def test_auto_sanitizes_pesticide_claims_from_llm_output():
    llm = SequenceLLMService([
        json.dumps({
            "title": "Bathroom Vanity with Ceramic Sink",
            "bullet_1": "Durable Build: Moisture-resistant cabinet",
            "bullet_2": "Premium Basin: Ceramic sink for daily use",
            "bullet_3": "Soft-Close Storage: Quiet drawer operation",
            "bullet_4": "Easy Maintenance: resists stains and bacteria",
            "bullet_5": "Hassle-Free Setup: hardware included",
            "description": (
                "<b>Built to Last</b><br/>Resists moisture and mold in humid bathrooms."
            ),
            "search_terms": "bathroom vanity",
            "generic_keyword": "bathroom vanity",
        }),
    ])
    gen = ProductContentGenerator(
        llm_service=llm,
        max_compliance_retries=0,
        reviewer=PassReviewer(),
    )
    result = gen.generate(_product(), product_type="CABINET")

    combined = " ".join([
        result.title, result.description, result.bullet_4,
    ]).lower()
    assert result.auto_sanitized
    assert not result.compliance_blocked
    assert "bacteria" not in combined
    assert "mold" not in combined


def test_blocks_when_claims_remain_after_sanitize_and_retry():
    llm = SequenceLLMService([
        json.dumps({
            "title": "Antimicrobial Bathroom Vanity",
            "bullet_1": "Feature",
            "bullet_2": "Feature",
            "bullet_3": "Feature",
            "bullet_4": "Feature",
            "bullet_5": "Feature",
            "description": "Antimicrobial protection against bacteria and mildew.",
            "search_terms": "bathroom vanity",
            "generic_keyword": "bathroom vanity",
        }),
        json.dumps({
            "title": "Still Antimicrobial Bathroom Vanity",
            "bullet_1": "Feature",
            "bullet_2": "Feature",
            "bullet_3": "Feature",
            "bullet_4": "Feature",
            "bullet_5": "Feature",
            "description": "Still antimicrobial against bacteria and mildew.",
            "search_terms": "bathroom vanity",
            "generic_keyword": "bathroom vanity",
        }),
    ])
    gen = ProductContentGenerator(
        llm_service=llm,
        max_compliance_retries=1,
        reviewer=PassReviewer(),
    )
    gen._scanner.sanitize_fields = lambda fields: (fields, [])
    result = gen.generate(_product(), product_type="CABINET")

    assert result.compliance_blocked
    assert result.validation_errors
