"""Unit tests for V2 rule feedback adapter."""

from src.services.rule_feedback_adapter_v2 import RuleFeedbackAdapterV2


class FakeFeedbackAdapter:
    def get_learned_required_paths(self, category):
        assert category == "CHAIR"
        return ["frame_material", "seat_depth"]


def test_apply_learned_paths_adds_missing_yaml_entries():
    rules = {
        "attributes": {
            "frame": {
                "children": {
                    "color": {
                        "children": {
                            "value": {
                                "sources": [{"path": "product.attributes.Main Color"}]
                            }
                        }
                    }
                }
            }
        }
    }
    adapter = RuleFeedbackAdapterV2(feedback_adapter=FakeFeedbackAdapter())

    result = adapter.apply_learned_paths("CHAIR", rules)

    material_rule = result.rules["attributes"]["frame"]["children"]["material"]["children"]["value"]
    depth_rule = result.rules["attributes"]["seat"]["children"]["depth"]["children"]["value"]
    assert "frame.material.value" in result.added_paths
    assert "seat.depth.value" in result.mapped_paths
    assert "Learned from Amazon 90220" in material_rule["sources"][0]["evidence"]
    assert depth_rule["sources"][0]["path"] == "product.dimensions.assembled_width"


def test_apply_learned_paths_maps_existing_placeholder():
    rules = {
        "attributes": {
            "seat": {
                "children": {
                    "depth": {
                        "children": {
                            "value": {
                                "sources": [
                                    {
                                        "default": None,
                                        "evidence": "TODO: review source mapping for seat.depth.value",
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
    }
    adapter = RuleFeedbackAdapterV2(feedback_adapter=FakeFeedbackAdapter())

    result = adapter.apply_learned_paths("CHAIR", rules, learned_paths=["seat_depth"])

    depth_rule = result.rules["attributes"]["seat"]["children"]["depth"]["children"]["value"]
    assert depth_rule["sources"][0]["path"] == "product.dimensions.assembled_width"
    assert "seat.depth.value" in result.mapped_paths
