"""Unit tests for ProductContentReviewer."""
import json

from src.models.product import StandardProduct
from src.services.product_content_generator import EnrichedProductContent
from src.services.product_content_reviewer import ProductContentReviewer


class FakeLLMResponse:
    def __init__(self, content):
        self.content = content


class FakeLLMService:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        return FakeLLMResponse(self.content)


def _product():
    return StandardProduct(
        sku="meow1",
        vendor_sku="GIGA1",
        vendor_source="giga",
        name="30 inch bathroom cabinet",
        description="Wood bathroom cabinet with soft close drawer.",
        attributes={"Main Material": "Wood", "Main Color": "White"},
    )


def _content(**overrides):
    data = {
        "title": "30 inch Bathroom Cabinet, White Wood Storage Vanity",
        "bullet_1": "Bathroom Storage: Keeps daily essentials organized",
        "bullet_2": "Soft-Close Drawer: Smooth access for everyday use",
        "bullet_3": "Wood Construction: Uses supplier-stated material",
        "bullet_4": "Easy Assembly: Designed for home bathroom projects",
        "bullet_5": "Clean Finish: White surface pairs with modern decor",
        "description": "A bathroom cabinet for organized daily storage.",
        "search_terms": "bathroom cabinet, vanity storage",
        "generic_keyword": "bathroom cabinet",
    }
    data.update(overrides)
    return EnrichedProductContent(**data)


def test_review_parses_pass_verdict():
    llm = FakeLLMService(json.dumps({
        "verdict": "pass",
        "accuracy_score": 0.95,
        "compliance_score": 1.0,
        "amazon_readiness_score": 0.9,
        "issues": [],
        "revision_instructions": "",
        "manual_review_fields": [],
        "unsupported_claims": [],
    }))
    reviewer = ProductContentReviewer(llm_service=llm)

    result = reviewer.review(_product(), "CABINET", _content())

    assert result.verdict == "pass"
    assert result.passed is True
    assert result.accuracy_score == 0.95
    assert llm.calls[0].json_mode is True
    assert llm.calls[0].task_type == "product_content_review"


def test_review_normalizes_invalid_verdict_to_manual_review():
    llm = FakeLLMService(json.dumps({"verdict": "maybe"}))
    reviewer = ProductContentReviewer(llm_service=llm)

    result = reviewer.review(_product(), "CABINET", _content())

    assert result.verdict == "manual_review"
    assert result.passed is False
    assert result.issues[0]["code"] == "INVALID_REVIEW_VERDICT"


def test_review_malformed_json_returns_manual_review():
    reviewer = ProductContentReviewer(llm_service=FakeLLMService("not json"))

    result = reviewer.review(_product(), "CABINET", _content())

    assert result.verdict == "manual_review"
    assert result.issues[0]["code"] == "REVIEW_PARSE_FAILED"


def test_review_llm_failure_returns_manual_review():
    class FailingLLM:
        def generate(self, request):
            raise RuntimeError("down")

    reviewer = ProductContentReviewer(llm_service=FailingLLM())

    result = reviewer.review(_product(), "CABINET", _content())

    assert result.verdict == "manual_review"
    assert "down" in result.issues[0]["message"]


def test_review_serializes_issue_metadata():
    llm = FakeLLMService(json.dumps({
        "verdict": "revise",
        "issues": [
            {
                "severity": "error",
                "code": "UNSUPPORTED_CLAIM",
                "field": "bullet_2",
                "message": "Mildew prevention is unsupported.",
            }
        ],
        "revision_instructions": "Remove mildew prevention claim.",
        "manual_review_fields": ["special_feature"],
    }))
    reviewer = ProductContentReviewer(llm_service=llm)

    result = reviewer.review(_product(), "CABINET", _content())

    payload = result.as_dict()
    assert payload["verdict"] == "revise"
    assert payload["issues"][0]["field"] == "bullet_2"
    assert payload["revision_instructions"] == "Remove mildew prevention claim."
    assert payload["manual_review_fields"] == ["special_feature"]
