"""Unit tests for V2 rule skeleton generation."""

from src.services.rule_skeleton_generator_v2 import RuleSkeletonGeneratorV2
from src.services.requirement_models_v2 import RequirementNode, RequirementTree


class FakeSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "CHAIR"
        return {
            "schema_json": {
                "properties": {
                    "brand": {"items": {"properties": {"value": {"type": "string"}}}},
                    "frame": {
                        "items": {
                            "required": ["color"],
                            "properties": {
                                "color": {
                                    "items": {
                                        "properties": {
                                            "value": {"type": "string"},
                                        }
                                    }
                                },
                                "material": {
                                    "items": {
                                        "properties": {
                                            "value": {"type": "string"},
                                        }
                                    }
                                },
                            },
                        }
                    },
                    "seat": {
                        "items": {
                            "required": ["height", "material_type"],
                            "properties": {
                                "depth": {
                                    "items": {
                                        "required": ["value", "unit"],
                                        "properties": {
                                            "value": {"type": "number"},
                                            "unit": {"type": "string"},
                                        },
                                    }
                                },
                                "height": {
                                    "items": {
                                        "required": ["value", "unit"],
                                        "properties": {
                                            "value": {"type": "number"},
                                            "unit": {"type": "string"},
                                        },
                                    }
                                },
                                "material_type": {
                                    "items": {
                                        "properties": {
                                            "value": {"type": "string"},
                                        }
                                    }
                                },
                            },
                        }
                    },
                    "item_depth_width_height": {
                        "items": {
                            "required": ["depth", "width", "height"],
                            "properties": {
                                "depth": {
                                    "items": {
                                        "properties": {
                                            "value": {"type": "number"},
                                            "unit": {"type": "string"},
                                        }
                                    }
                                },
                                "width": {
                                    "items": {
                                        "properties": {
                                            "value": {"type": "number"},
                                            "unit": {"type": "string"},
                                        }
                                    }
                                },
                                "height": {
                                    "items": {
                                        "properties": {
                                            "value": {"type": "number"},
                                            "unit": {"type": "string"},
                                        }
                                    }
                                },
                            },
                        }
                    },
                    "maximum_weight_recommendation": {
                        "items": {
                            "required": ["value", "unit"],
                            "properties": {
                                "value": {"type": "number"},
                                "unit": {"type": "string"},
                            },
                        }
                    },
                    "number_of_items": {
                        "items": {"properties": {"value": {"type": "integer"}}}
                    },
                },
                "required": [
                    "brand",
                    "frame",
                    "seat",
                    "item_depth_width_height",
                    "maximum_weight_recommendation",
                    "number_of_items",
                ],
            },
            "required_properties": [
                "brand",
                "frame",
                "seat",
                "item_depth_width_height",
                "maximum_weight_recommendation",
                "number_of_items",
            ],
        }


def test_generator_writes_skeleton_with_children_and_root_config(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.services.rule_skeleton_generator_v2.RequirementTreeBuilderV2",
        _FakeTreeBuilder,
    )
    generator = RuleSkeletonGeneratorV2(
        schema_service=FakeSchemaService(),
        output_dir=tmp_path,
    )

    result = generator.generate("CHAIR", overwrite=True)

    assert result.written is True
    assert result.rules["dimension_strategy"] == "item_depth_width_height"
    assert result.rules["coverage_ignore_required"] == []
    assert "brand" not in result.rules["attributes"]

    frame = result.rules["attributes"]["frame"]
    assert "sources" not in frame
    assert "children" in frame
    assert frame["children"]["color"]["children"]["value"]["sources"][0]["evidence"].startswith(
        "TODO:"
    )

    seat = result.rules["attributes"]["seat"]
    assert "sources" not in seat
    assert "height" in seat["children"]
    assert "material_type" in seat["children"]

    measure = result.rules["attributes"]["maximum_weight_recommendation"]
    assert measure["shape"] == "measure"
    assert "value" in measure["children"]
    assert "unit" in measure["children"]


def test_generator_does_not_overwrite_without_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.services.rule_skeleton_generator_v2.RequirementTreeBuilderV2",
        _FakeTreeBuilder,
    )
    existing = tmp_path / "chair.yaml"
    existing.write_text("product_type: CHAIR\n", encoding="utf-8")
    generator = RuleSkeletonGeneratorV2(
        schema_service=FakeSchemaService(),
        output_dir=tmp_path,
    )

    result = generator.generate("CHAIR", overwrite=False)

    assert result.written is False
    assert result.existed is True
    assert "not overwritten" in result.warnings[0]


class _FakeTreeBuilder:
    def __init__(self, schema_service):
        self.schema_service = schema_service

    def build(self, product_type, attributes=None, learned_required_paths=None):
        root = RequirementNode(
            path_key=product_type,
            schema_path="$",
            name=product_type,
            shape="root",
            required=True,
        )
        root.children = [
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
                        required_children=["value"],
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
            ),
            RequirementNode(
                path_key="seat",
                schema_path="$.properties.seat",
                name="seat",
                shape="object",
                required=True,
                required_children=["height", "material_type"],
                children=[
                    RequirementNode(
                        path_key="seat.height",
                        schema_path="$.properties.seat.items.properties.height",
                        name="height",
                        shape="measure",
                        required=True,
                        required_children=["value", "unit"],
                        children=[
                            RequirementNode(
                                path_key="seat.height.value",
                                schema_path="$.x",
                                name="value",
                                shape="scalar",
                                required=True,
                            ),
                            RequirementNode(
                                path_key="seat.height.unit",
                                schema_path="$.x",
                                name="unit",
                                shape="scalar",
                                required=True,
                                enum_values=["inches"],
                            ),
                        ],
                    ),
                    RequirementNode(
                        path_key="seat.material_type",
                        schema_path="$.properties.seat.items.properties.material_type",
                        name="material_type",
                        shape="list_value",
                        required=True,
                        required_children=["value"],
                        children=[
                            RequirementNode(
                                path_key="seat.material_type.value",
                                schema_path="$.x",
                                name="value",
                                shape="scalar",
                                required=True,
                            )
                        ],
                    ),
                ],
            ),
            RequirementNode(
                path_key="maximum_weight_recommendation",
                schema_path="$.properties.maximum_weight_recommendation",
                name="maximum_weight_recommendation",
                shape="measure",
                required=True,
                required_children=["value", "unit"],
                children=[
                    RequirementNode(
                        path_key="maximum_weight_recommendation.value",
                        schema_path="$.x",
                        name="value",
                        shape="scalar",
                        required=True,
                    ),
                    RequirementNode(
                        path_key="maximum_weight_recommendation.unit",
                        schema_path="$.x",
                        name="unit",
                        shape="scalar",
                        required=True,
                    ),
                ],
            ),
        ]
        return RequirementTree(
            product_type=product_type,
            root=root,
            required_paths=[
                "frame",
                "frame.color",
                "frame.color.value",
                "seat",
                "seat.height",
                "seat.height.value",
                "seat.height.unit",
                "seat.material_type",
                "seat.material_type.value",
                "maximum_weight_recommendation",
                "maximum_weight_recommendation.value",
                "maximum_weight_recommendation.unit",
            ],
        )
