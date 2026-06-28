"""Tests for V2 generic payload composition."""

from src.services.payload_composer_v2 import PayloadComposerV2
from src.services.requirement_models_v2 import RequirementNode, ResolutionNode


def test_composer_renders_list_value_with_auto_language_tag():
    root = _root(
        RequirementNode(
            path_key="color_name",
            schema_path="$.properties.color_name",
            name="color_name",
            shape="list_value",
            required=True,
            auto_fields={"language_tag": "en_US"},
        )
    )
    resolution = _resolution_root(
        ResolutionNode(path_key="color_name", value="Black", confidence="high")
    )

    attrs = PayloadComposerV2().compose(root, resolution)

    assert attrs == {
        "color_name": [{"language_tag": "en_US", "value": "Black"}]
    }


def test_composer_renders_measure_from_child_resolution_nodes():
    root = _root(
        RequirementNode(
            path_key="maximum_weight_recommendation",
            schema_path="$.properties.maximum_weight_recommendation",
            name="maximum_weight_recommendation",
            shape="measure",
            required=True,
            required_children=["unit", "value"],
            children=[
                RequirementNode(
                    path_key="maximum_weight_recommendation.unit",
                    schema_path="$.properties.maximum_weight_recommendation.items.properties.unit",
                    name="unit",
                    shape="scalar",
                    required=True,
                ),
                RequirementNode(
                    path_key="maximum_weight_recommendation.value",
                    schema_path="$.properties.maximum_weight_recommendation.items.properties.value",
                    name="value",
                    shape="scalar",
                    required=True,
                ),
            ],
        )
    )
    resolution = _resolution_root(
        ResolutionNode(
            path_key="maximum_weight_recommendation",
            children=[
                ResolutionNode(path_key="maximum_weight_recommendation.unit", value="pounds"),
                ResolutionNode(path_key="maximum_weight_recommendation.value", value=250),
            ],
        )
    )

    attrs = PayloadComposerV2().compose(root, resolution)

    assert attrs == {
        "maximum_weight_recommendation": [{"unit": "pounds", "value": 250}]
    }


def test_composer_renders_object_with_nested_list_value_child():
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
                    auto_fields={"language_tag": "en_US"},
                )
            ],
        )
    )
    resolution = _resolution_root(
        ResolutionNode(
            path_key="frame",
            children=[ResolutionNode(path_key="frame.color", value="Brown")],
        )
    )

    attrs = PayloadComposerV2().compose(root, resolution)

    assert attrs == {
        "frame": [
            {
                "color": [{"language_tag": "en_US", "value": "Brown"}],
            }
        ]
    }


def test_composer_renders_array_object_with_selector_auto_field():
    root = _root(
        RequirementNode(
            path_key="fulfillment_availability",
            schema_path="$.properties.fulfillment_availability",
            name="fulfillment_availability",
            shape="array_object",
            required=True,
            selectors=["marketplace_id"],
            auto_fields={"marketplace_id": "ATVPDKIKX0DER"},
            required_children=["fulfillment_channel_code", "quantity"],
            children=[
                RequirementNode(
                    path_key="fulfillment_availability.fulfillment_channel_code",
                    schema_path="$.properties.fulfillment_availability.items.properties.fulfillment_channel_code",
                    name="fulfillment_channel_code",
                    shape="scalar",
                    required=True,
                ),
                RequirementNode(
                    path_key="fulfillment_availability.quantity",
                    schema_path="$.properties.fulfillment_availability.items.properties.quantity",
                    name="quantity",
                    shape="scalar",
                    required=True,
                ),
            ],
        )
    )
    resolution = _resolution_root(
        ResolutionNode(
            path_key="fulfillment_availability",
            children=[
                ResolutionNode(
                    path_key="fulfillment_availability.fulfillment_channel_code",
                    value="DEFAULT",
                ),
                ResolutionNode(path_key="fulfillment_availability.quantity", value=7),
            ],
        )
    )

    attrs = PayloadComposerV2().compose(root, resolution)

    assert attrs == {
        "fulfillment_availability": [
            {
                "marketplace_id": "ATVPDKIKX0DER",
                "fulfillment_channel_code": "DEFAULT",
                "quantity": 7,
            }
        ]
    }


def test_composer_renders_array_object_from_scalar_list_parent_value():
    root = _root(
        RequirementNode(
            path_key="bullet_point",
            schema_path="$.properties.bullet_point",
            name="bullet_point",
            shape="array_object",
            required=True,
            auto_fields={"language_tag": "en_US"},
            required_children=["value"],
            children=[
                RequirementNode(
                    path_key="bullet_point.value",
                    schema_path="$.properties.bullet_point.items.properties.value",
                    name="value",
                    shape="scalar",
                    required=True,
                )
            ],
        )
    )
    resolution = _resolution_root(
        ResolutionNode(
            path_key="bullet_point",
            value=["Space saving", "Easy assembly"],
            children=[
                ResolutionNode(
                    path_key="bullet_point.value",
                    value=["Space saving", "Easy assembly"],
                )
            ],
        )
    )

    attrs = PayloadComposerV2().compose(root, resolution)

    assert attrs == {
        "bullet_point": [
            {"language_tag": "en_US", "value": "Space saving"},
            {"language_tag": "en_US", "value": "Easy assembly"},
        ]
    }


def test_composer_renders_array_object_from_scalar_parent_value():
    root = _root(
        RequirementNode(
            path_key="door",
            schema_path="$.properties.door",
            name="door",
            shape="array_object",
            required=True,
            auto_fields={"marketplace_id": "ATVPDKIKX0DER"},
        )
    )
    resolution = _resolution_root(
        ResolutionNode(path_key="door", value="Shaker", confidence="high")
    )

    attrs = PayloadComposerV2().compose(root, resolution)

    assert attrs == {
        "door": [{"marketplace_id": "ATVPDKIKX0DER", "value": "Shaker"}]
    }


def test_composer_renders_nested_array_object_child_as_list():
    root = _root(
        RequirementNode(
            path_key="seat",
            schema_path="$.properties.seat",
            name="seat",
            shape="array_object",
            required=True,
            children=[
                RequirementNode(
                    path_key="seat.material_type",
                    schema_path="$.properties.seat.items.properties.material_type",
                    name="material_type",
                    shape="array_object",
                    required=True,
                    auto_fields={"language_tag": "en_US"},
                    children=[
                        RequirementNode(
                            path_key="seat.material_type.value",
                            schema_path="$.properties.seat.items.properties.material_type.items.properties.value",
                            name="value",
                            shape="scalar",
                            required=True,
                        )
                    ],
                )
            ],
        )
    )
    resolution = _resolution_root(
        ResolutionNode(
            path_key="seat",
            children=[
                ResolutionNode(
                    path_key="seat.material_type",
                    value="Linen",
                    children=[
                        ResolutionNode(
                            path_key="seat.material_type.value",
                            value="Linen",
                        )
                    ],
                )
            ],
        )
    )

    attrs = PayloadComposerV2().compose(root, resolution)

    assert attrs == {
        "seat": [
            {
                "material_type": [
                    {"language_tag": "en_US", "value": "Linen"}
                ]
            }
        ]
    }


def test_composer_skips_blocking_top_level_resolution():
    root = _root(
        RequirementNode(
            path_key="color_name",
            schema_path="$.properties.color_name",
            name="color_name",
            shape="list_value",
            required=True,
        )
    )
    resolution = _resolution_root(
        ResolutionNode(path_key="color_name", value="Black", blocking=True)
    )

    assert PayloadComposerV2().compose(root, resolution) == {}


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
