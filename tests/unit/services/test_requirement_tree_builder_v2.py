"""Tests for read-only V2 requirement tree building."""

from src.services.requirement_tree_builder_v2 import RequirementTreeBuilderV2


class FakeSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "CHAIR"
        return {
            "required_properties": ["item_name"],
            "schema_json": {
                "required": ["item_name"],
                "properties": {
                    "item_name": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "parentage_level": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "child_parent_sku_relationship": {
                        "items": {"properties": {"parent_sku": {"type": "string"}}}
                    },
                    "variation_theme": {
                        "items": {"properties": {"name": {"type": "string"}}}
                    },
                    "frame": {
                        "items": {
                            "required": ["color"],
                            "properties": {
                                "color": {
                                    "items": {
                                        "required": ["language_tag", "value"],
                                        "properties": {
                                            "language_tag": {"type": "string"},
                                            "value": {"enum": ["Black", "Brown"]},
                                        },
                                    }
                                },
                                "material": {
                                    "items": {
                                        "required": ["language_tag", "value"],
                                        "properties": {
                                            "language_tag": {"type": "string"},
                                            "value": {"type": "string"},
                                        },
                                    }
                                },
                            },
                        }
                    },
                    "frame_material": {
                        "items": {
                            "required": ["language_tag", "value"],
                            "properties": {
                                "language_tag": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        }
                    },
                },
                "allOf": [
                    {
                        "if": {"not": {"required": ["parentage_level"]}},
                        "then": {"required": ["frame"]},
                    },
                    {
                        "if": {
                            "allOf": [
                                {"required": ["child_parent_sku_relationship"]},
                                {
                                    "properties": {
                                        "variation_theme": {
                                            "contains": {
                                                "required": ["name"],
                                                "properties": {
                                                    "name": {"enum": ["COLOR"]}
                                                },
                                            }
                                        }
                                    },
                                    "required": ["variation_theme"],
                                },
                            ]
                        },
                        "then": {"required": ["frame_material"]},
                    },
                ],
            },
        }


class UnsupportedConditionSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "CHAIR"
        return {
            "required_properties": ["item_name"],
            "schema_json": {
                "required": ["item_name"],
                "properties": {
                    "item_name": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "frame_material": {
                        "items": {
                            "required": ["language_tag", "value"],
                            "properties": {
                                "language_tag": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        }
                    },
                },
                "allOf": [
                    {
                        "if": {"dependentRequired": {"battery": ["battery_type"]}},
                        "then": {"required": ["frame_material"]},
                    },
                ],
            },
        }


class MetadataSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "CHAIR"
        return {
            "required_properties": [
                "color_name",
                "maximum_weight_recommendation",
                "fulfillment_availability",
            ],
            "schema_json": {
                "properties": {
                    "color_name": {
                        "items": {
                            "required": ["language_tag", "value"],
                            "properties": {
                                "language_tag": {"type": "string"},
                                "value": {"enum": ["Black", "Brown"]},
                            },
                        }
                    },
                    "maximum_weight_recommendation": {
                        "items": {
                            "required": ["unit", "value"],
                            "properties": {
                                "unit": {"enum": ["pounds", "kilograms"]},
                                "value": {"type": "number"},
                            },
                        }
                    },
                    "fulfillment_availability": {
                        "selectors": ["marketplace_id"],
                        "items": {
                            "required": [
                                "fulfillment_channel_code",
                                "marketplace_id",
                                "quantity",
                            ],
                            "properties": {
                                "fulfillment_channel_code": {"type": "string"},
                                "marketplace_id": {"type": "string"},
                                "quantity": {"type": "integer"},
                            },
                        },
                    },
                },
            },
        }


def test_builder_adds_only_applicable_conditional_required_paths():
    builder = RequirementTreeBuilderV2(FakeSchemaService())

    tree = builder.build("CHAIR", attributes={"item_name": [{"value": "Chair"}]})

    assert "item_name" in tree.required_paths
    assert "frame" in tree.required_paths
    assert "frame.color" in tree.required_paths
    assert "frame_material" not in tree.required_paths
    frame = next(child for child in tree.root.children if child.name == "frame")
    assert frame.shape == "object"
    assert frame.required_children == ["color"]
    assert frame.children[0].enum_values == ["Black", "Brown"]
    assert "frame_material" in tree.non_applicable_required_paths
    assert "frame_material" not in tree.unknown_required_paths


def test_builder_adds_variation_child_conditional_required_when_payload_matches():
    builder = RequirementTreeBuilderV2(FakeSchemaService())
    attrs = {
        "item_name": [{"value": "Chair"}],
        "child_parent_sku_relationship": [{"parent_sku": "PARENT-1"}],
        "variation_theme": [{"name": "COLOR"}],
    }

    tree = builder.build("CHAIR", attributes=attrs)

    assert "frame_material" in tree.required_paths
    assert "frame_material" not in tree.non_applicable_required_paths


def test_builder_injects_learned_required_paths_that_exist_in_schema():
    builder = RequirementTreeBuilderV2(FakeSchemaService())

    tree = builder.build(
        "CHAIR",
        attributes={"item_name": [{"value": "Chair"}]},
        learned_required_paths=["frame_material"],
    )

    assert "frame_material" in tree.required_paths
    node = next(child for child in tree.root.children if child.name == "frame_material")
    assert node.required is True


def test_builder_ignores_learned_required_paths_not_in_schema_properties():
    builder = RequirementTreeBuilderV2(FakeSchemaService())

    tree = builder.build(
        "CHAIR",
        attributes={"item_name": [{"value": "Chair"}]},
        learned_required_paths=["nonexistent_attribute"],
    )

    assert "nonexistent_attribute" not in tree.required_paths


def test_builder_does_not_duplicate_learned_path_already_required_by_schema():
    builder = RequirementTreeBuilderV2(FakeSchemaService())

    tree = builder.build(
        "CHAIR",
        attributes={"item_name": [{"value": "Chair"}]},
        learned_required_paths=["item_name"],
    )

    assert tree.required_paths.count("item_name") == 1


def test_builder_reports_unknown_required_paths_for_unsupported_condition():
    builder = RequirementTreeBuilderV2(UnsupportedConditionSchemaService())

    tree = builder.build("CHAIR", attributes={"item_name": [{"value": "Chair"}]})

    assert "frame_material" not in tree.required_paths
    assert "frame_material" not in tree.non_applicable_required_paths
    assert "frame_material" in tree.unknown_required_paths
    assert tree.condition_traces[0].unknown_required_paths == ["frame_material"]


def test_builder_extracts_measure_auto_fields_and_selectors_metadata():
    builder = RequirementTreeBuilderV2(MetadataSchemaService())

    tree = builder.build("CHAIR")

    color = next(child for child in tree.root.children if child.name == "color_name")
    assert color.shape == "list_value"
    assert color.required_children == ["value"]
    assert color.enum_values == ["Black", "Brown"]
    assert color.auto_fields == {"language_tag": "en_US"}

    weight = next(
        child
        for child in tree.root.children
        if child.name == "maximum_weight_recommendation"
    )
    assert weight.shape == "measure"
    assert weight.required_children == ["unit", "value"]
    assert weight.unit_values == ["pounds", "kilograms"]
    assert {child.path_key for child in weight.children} == {
        "maximum_weight_recommendation.unit",
        "maximum_weight_recommendation.value",
    }

    availability = next(
        child
        for child in tree.root.children
        if child.name == "fulfillment_availability"
    )
    assert availability.shape == "array_object"
    assert availability.selectors == ["marketplace_id"]
    assert availability.required_children == ["fulfillment_channel_code", "quantity"]
    assert availability.auto_fields == {"marketplace_id": "ATVPDKIKX0DER"}
