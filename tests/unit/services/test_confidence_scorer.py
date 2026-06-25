"""Unit tests for evidence-grounded confidence scoring."""

from src.models.amazon_listing import AmazonListingDraft, ListingContent
from src.models.product import StandardProduct
from src.services.attribute_resolver import AttributeResolution
from src.services.confidence_scorer import ConfidenceScorer


class FakeSchemaService:
    def get_cached_valid_values(self, product_type, attribute):
        return {"mounting_type": ["Wall Mount", "Freestanding"]}.get(attribute, [])


def _draft(product_type="CHAIR"):
    return AmazonListingDraft(
        sku="SKU1",
        vendor_sku="VENDOR1",
        product_type=product_type,
        standard_product=StandardProduct(
            sku="SKU1",
            vendor_sku="VENDOR1",
            vendor_source="giga",
            attributes={"Mounting Type": "Wall Mount"},
        ),
        content=ListingContent(
            title="Wall Mount Chair",
            description="Wall Mount hardware is included for installation.",
        ),
    )


def _resolution(
    attribute="mounting_type",
    value="Wall Mount",
    evidence=None,
    confidence="medium",
):
    return AttributeResolution(
        attribute=attribute,
        value=value,
        level="required",
        shape="list_value",
        source="llm",
        evidence=evidence or "Wall Mount hardware is included",
        confidence=confidence,
        state="needs_manual_review",
    )


def test_confidence_scorer_auto_approves_evidence_grounded_attribute():
    scorer = ConfidenceScorer(schema_service=FakeSchemaService())

    score = scorer.score(_resolution(), _draft())

    assert score.score == 80
    assert score.route == "auto_approved"
    assert score.signals["evidence_context_match"] == 45
    assert score.signals["enum_valid"] == 15


def test_confidence_scorer_routes_weak_but_matched_evidence_to_ai_agent():
    scorer = ConfidenceScorer(schema_service=FakeSchemaService())

    score = scorer.score(
        _resolution(
            attribute="included_components",
            value="Chair",
            evidence="Chair",
            confidence="low",
        ),
        _draft(),
    )

    assert score.score == 45
    assert score.route == "ai_agent"
    assert "evidence_too_short" in score.reasons


def test_confidence_scorer_routes_unmatched_evidence_to_human():
    scorer = ConfidenceScorer(schema_service=FakeSchemaService())

    score = scorer.score(
        _resolution(
            attribute="included_components",
            value="Chair",
            evidence="Not present in context text",
            confidence="low",
        ),
        _draft(),
    )

    assert score.route == "human"
    assert "evidence_not_in_context" in score.reasons


def test_confidence_scorer_respects_product_type_whitelist():
    scorer = ConfidenceScorer(schema_service=FakeSchemaService())

    score = scorer.score(_resolution(), _draft(product_type="HOME_MIRROR"))

    assert score.score == 0
    assert score.route == "human"
    assert score.reasons == ["review_policy_disabled"]
