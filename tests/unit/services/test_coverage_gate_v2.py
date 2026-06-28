"""Tests for V2 tree-level coverage gate."""

from src.services.coverage_gate_v2 import CoverageGateV2
from src.services.requirement_models_v2 import (
    PayloadBuildPlan,
    RequirementNode,
    RequirementTree,
    ResolutionNode,
)


def test_gate_blocks_object_missing_required_child_even_when_parent_exists():
    root = _root(
        RequirementNode(
            path_key="frame",
            schema_path="$.properties.frame",
            name="frame",
            shape="object",
            required=True,
            required_children=["color"],
            children=[
                RequirementNode(
                    path_key="frame.color",
                    schema_path="$.properties.frame.items.properties.color",
                    name="color",
                    shape="list_value",
                    required=True,
                )
            ],
        )
    )
    attrs = {"frame": [{"material": [{"value": "Wood"}]}]}

    result = CoverageGateV2().evaluate(root, _resolution_root(), attrs)

    assert result.blocked is True
    assert "frame.color" in result.missing_required_paths
    assert result.blocking_codes == ["MISSING_REQUIRED_ATTRIBUTE_RULE"]


def test_gate_covers_required_child_paths_when_payload_is_complete():
    root = _root(
        RequirementNode(
            path_key="frame",
            schema_path="$.properties.frame",
            name="frame",
            shape="object",
            required=True,
            required_children=["color"],
            children=[
                RequirementNode(
                    path_key="frame.color",
                    schema_path="$.properties.frame.items.properties.color",
                    name="color",
                    shape="list_value",
                    required=True,
                )
            ],
        )
    )
    attrs = {"frame": [{"color": [{"value": "Black"}]}]}

    result = CoverageGateV2().evaluate(root, _resolution_root(), attrs)

    assert result.blocked is False
    assert result.covered_required_paths == ["frame", "frame.color"]


def test_gate_ignores_configured_required_paths():
    root = _root(
        RequirementNode(
            path_key="merchant_shipping_group",
            schema_path="$.properties.merchant_shipping_group",
            name="merchant_shipping_group",
            shape="array_object",
            required=True,
        ),
        RequirementNode(
            path_key="item_name",
            schema_path="$.properties.item_name",
            name="item_name",
            shape="array_object",
            required=True,
        ),
    )
    attrs = {"item_name": [{"value": "Chair"}]}

    result = CoverageGateV2(
        ignored_required_paths=["merchant_shipping_group"]
    ).evaluate(root, _resolution_root(), attrs)

    assert result.blocked is False
    assert result.missing_required_paths == []
    assert result.covered_required_paths == ["item_name"]


def test_gate_covers_nested_list_value_child_value_path():
    root = _root(
        RequirementNode(
            path_key="frame",
            schema_path="$.properties.frame",
            name="frame",
            shape="object",
            required=True,
            children=[
                RequirementNode(
                    path_key="frame.color",
                    schema_path="$.properties.frame.items.properties.color",
                    name="color",
                    shape="list_value",
                    required=True,
                    children=[
                        RequirementNode(
                            path_key="frame.color.value",
                            schema_path="$.properties.frame.items.properties.color.items.properties.value",
                            name="value",
                            shape="scalar",
                            required=True,
                        )
                    ],
                )
            ],
        )
    )
    attrs = {"frame": [{"color": [{"value": "Black"}]}]}

    result = CoverageGateV2().evaluate(root, _resolution_root(), attrs)

    assert result.blocked is False
    assert result.covered_required_paths == [
        "frame",
        "frame.color",
        "frame.color.value",
    ]


def test_gate_blocks_measure_missing_required_unit():
    root = _root(
        RequirementNode(
            path_key="maximum_weight_recommendation",
            schema_path="$.properties.maximum_weight_recommendation",
            name="maximum_weight_recommendation",
            shape="measure",
            required=True,
            required_children=["value", "unit"],
        )
    )
    attrs = {"maximum_weight_recommendation": [{"value": 250}]}

    result = CoverageGateV2().evaluate(root, _resolution_root(), attrs)

    assert result.blocked is True
    assert result.missing_required_paths == ["maximum_weight_recommendation.unit"]


def test_gate_blocks_pending_review_and_low_confidence_required_paths():
    root = _root(
        RequirementNode(
            path_key="color_name",
            schema_path="$.properties.color_name",
            name="color_name",
            shape="list_value",
            required=True,
        ),
        RequirementNode(
            path_key="frame_material",
            schema_path="$.properties.frame_material",
            name="frame_material",
            shape="list_value",
            required=True,
        ),
    )
    resolution = _resolution_root(
        ResolutionNode(
            path_key="color_name",
            value="Black",
            confidence="medium",
            review_status="pending",
        ),
        ResolutionNode(
            path_key="frame_material",
            value="Wood",
            confidence="low",
        ),
    )
    attrs = {
        "color_name": [{"value": "Black"}],
        "frame_material": [{"value": "Wood"}],
    }

    result = CoverageGateV2().evaluate(root, resolution, attrs)

    assert result.blocked is True
    assert result.pending_review_paths == ["color_name"]
    assert result.low_confidence_required_paths == ["frame_material"]
    assert result.blocking_codes == [
        "NEEDS_REVIEW_REQUIRED_ATTRIBUTE",
        "LOW_CONFIDENCE_REQUIRED_ATTRIBUTE",
    ]


def test_gate_tracks_safe_default_and_blocks_unsafe_default():
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
    resolution = _resolution_root(
        ResolutionNode(
            path_key="number_of_items",
            value=1,
            source="default",
            confidence="medium",
            safe_default=True,
        ),
        ResolutionNode(
            path_key="item_shape",
            value="Rectangular",
            source="default",
            confidence="medium",
            safe_default=False,
        ),
    )
    attrs = {
        "number_of_items": [{"value": 1}],
        "item_shape": [{"value": "Rectangular"}],
    }

    result = CoverageGateV2().evaluate(root, resolution, attrs)

    assert result.safe_default_paths == ["number_of_items"]
    assert result.blocked is True
    assert result.blocking_codes == ["UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE"]


def test_gate_applies_result_to_payload_build_plan():
    root = _root(
        RequirementNode(
            path_key="item_name",
            schema_path="$.properties.item_name",
            name="item_name",
            shape="list_value",
            required=True,
        )
    )
    plan = PayloadBuildPlan(
        sku="SKU1",
        product_type="CHAIR",
        attributes={},
        requirement_tree=RequirementTree(
            product_type="CHAIR",
            root=root,
            required_paths=["item_name"],
        ),
    )
    result = CoverageGateV2().evaluate(root, _resolution_root(), {})

    CoverageGateV2.apply_to_plan(plan, result)

    assert plan.missing_required_paths == ["item_name"]
    assert plan.findings[0]["code"] == "MISSING_REQUIRED_ATTRIBUTE_RULE"


def _root(*children: RequirementNode) -> RequirementNode:
    return RequirementNode(
        path_key="CHAIR",
        schema_path="$",
        name="CHAIR",
        shape="root",
        required=True,
        children=list(children),
    )


def _resolution_root(*children: ResolutionNode) -> ResolutionNode:
    return ResolutionNode(path_key="CHAIR", children=list(children))
