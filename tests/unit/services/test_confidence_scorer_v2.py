"""Tests for V2 path-level confidence scorer."""

from src.models.amazon_listing import AmazonListingDraft, ListingContent, ListingOffer
from src.models.product import StandardProduct
from src.services.confidence_scorer_v2 import ConfidenceScorerV2
from src.services.requirement_models_v2 import RequirementNode, ResolutionNode


def test_leaf_path_auto_approved_with_full_evidence():
    requirement = _leaf("frame.color", "color", enum_values=["black", "walnut"])
    resolution = ResolutionNode(
        path_key="frame.color",
        value="walnut",
        source="llm",
        evidence="A dining chair built from matte walnut wood.",
        confidence="medium",
    )

    score = ConfidenceScorerV2().score_node(resolution, _draft(), requirement)

    assert score.route == "auto_approved"
    assert score.score >= 55
    assert "evidence_context_match" in score.signals
    assert "evidence_min_length" in score.signals
    assert "enum_valid" in score.signals
    assert "llm_confidence_not_low" in score.signals


def test_sensitive_path_routes_to_human():
    requirement = _leaf("brand", "brand")
    resolution = ResolutionNode(
        path_key="brand",
        value="SomeBrand",
        source="llm",
        evidence="The product brand is SomeBrand according to the supplier spec.",
        confidence="medium",
    )

    score = ConfidenceScorerV2().score_node(resolution, _draft(), requirement)

    assert score.route == "human"
    assert score.score == 0
    assert "sensitive_path" in score.reasons


def test_safe_default_path_auto_approved():
    requirement = _leaf("number_of_items", "number_of_items")
    resolution = ResolutionNode(
        path_key="number_of_items",
        value=1,
        source="default",
        evidence="Single item fallback",
        confidence="medium",
        safe_default=True,
    )

    score = ConfidenceScorerV2().score_node(resolution, _draft(), requirement)

    assert score.route == "auto_approved"
    assert score.score == 100
    assert "safe_default" in score.reasons


def test_evidence_not_in_context_lowers_score():
    requirement = _leaf("frame.color", "color")
    resolution = ResolutionNode(
        path_key="frame.color",
        value="walnut",
        source="llm",
        evidence="A completely unrelated evidence string that does not appear.",
        confidence="medium",
    )

    score = ConfidenceScorerV2().score_node(resolution, _draft(), requirement)

    assert "evidence_context_match" not in score.signals
    assert "evidence_not_in_context" in score.reasons
    assert score.route in {"ai_agent", "human"}


def test_measure_parent_aggregates_child_routes_conservatively():
    requirement = RequirementNode(
        path_key="maximum_weight_recommendation",
        schema_path="$.properties.maximum_weight_recommendation",
        name="maximum_weight_recommendation",
        shape="measure",
        required=True,
        children=[
            _leaf("maximum_weight_recommendation.value", "value"),
            _leaf("maximum_weight_recommendation.unit", "unit"),
        ],
    )
    resolution = ResolutionNode(
        path_key="maximum_weight_recommendation",
        value=None,
        source="",
        children=[
            ResolutionNode(
                path_key="maximum_weight_recommendation.value",
                value=250,
                source="product.attributes.Weight Capacity",
                evidence="250 pounds weight capacity",
                confidence="high",
                confidence_score=70,
                review_route="auto_approved",
            ),
            ResolutionNode(
                path_key="maximum_weight_recommendation.unit",
                value=None,
                source="",
                confidence="low",
                confidence_score=0,
                review_route="human",
            ),
        ],
    )

    score = ConfidenceScorerV2().score_node(resolution, _draft(), requirement)

    assert score.route == "human"
    assert "aggregated_from_children" in score.reasons


def test_parent_auto_approved_when_all_children_auto_approved():
    requirement = RequirementNode(
        path_key="frame",
        schema_path="$.properties.frame",
        name="frame",
        shape="object",
        required=True,
        children=[_leaf("frame.color", "color"), _leaf("frame.material", "material")],
    )
    resolution = ResolutionNode(
        path_key="frame",
        value=None,
        source="",
        children=[
            ResolutionNode(
                path_key="frame.color",
                value="walnut",
                confidence_score=80,
                review_route="auto_approved",
            ),
            ResolutionNode(
                path_key="frame.material",
                value="wood",
                confidence_score=75,
                review_route="auto_approved",
            ),
        ],
    )

    score = ConfidenceScorerV2().score_node(resolution, _draft(), requirement)

    assert score.route == "auto_approved"
    assert score.score == 75


def test_score_tree_mutates_resolution_nodes_in_place():
    requirement_root = _root(
        RequirementNode(
            path_key="frame",
            schema_path="$.properties.frame",
            name="frame",
            shape="object",
            required=True,
            children=[
                _leaf("frame.color", "color", enum_values=["walnut"]),
            ],
        )
    )
    resolution_root = ResolutionNode(
        path_key="CHAIR",
        children=[
            ResolutionNode(
                path_key="frame",
                children=[
                    ResolutionNode(
                        path_key="frame.color",
                        value="walnut",
                        source="llm",
                        evidence="A dining chair built from matte walnut wood.",
                        confidence="medium",
                    ),
                ],
            )
        ],
    )

    ConfidenceScorerV2().score_tree(resolution_root, _draft(), requirement_root)

    color_node = resolution_root.children[0].children[0]
    assert color_node.confidence_score is not None
    assert color_node.confidence_score >= 55
    assert color_node.review_route == "auto_approved"
    frame_node = resolution_root.children[0]
    assert frame_node.review_route == "auto_approved"


def test_policy_disabled_routes_all_to_human():
    requirement = _leaf("frame.color", "color")
    resolution = ResolutionNode(
        path_key="frame.color",
        value="walnut",
        source="llm",
        evidence="The frame is made of matte walnut wood with a smooth finish.",
        confidence="medium",
    )
    scorer = ConfidenceScorerV2(policy={"enabled": False})

    score = scorer.score_node(resolution, _draft(), requirement)

    assert score.route == "human"
    assert "review_policy_disabled" in score.reasons


def _leaf(path_key: str, name: str, enum_values=None) -> RequirementNode:
    return RequirementNode(
        path_key=path_key,
        schema_path=f"$.properties.{path_key.replace('.', '.items.properties.')}",
        name=name,
        shape="list_value",
        required=True,
        enum_values=enum_values or [],
    )


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
        content=ListingContent(
            title="Walnut Dining Chair",
            bullets=["Solid walnut frame", "Smooth finish"],
            description="A dining chair built from matte walnut wood.",
        ),
        offer=ListingOffer(price=99.99, quantity=3),
    )
