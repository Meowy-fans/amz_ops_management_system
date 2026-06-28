"""Unit tests for V2 rule tree helpers."""

from src.services.rule_tree_utils_v2 import (
    count_placeholder_leaves,
    ensure_rule_at_path,
    get_rule_at_path,
    has_placeholder_source,
    iter_leaf_rules,
    replace_placeholder_sources,
)


def test_iter_leaf_rules_and_placeholder_detection():
    attributes = {
        "seat": {
            "children": {
                "depth": {
                    "children": {
                        "value": {
                            "sources": [
                                {"evidence": "TODO: review source mapping for seat.depth.value"}
                            ]
                        }
                    }
                }
            }
        }
    }

    leaves = list(iter_leaf_rules(attributes))

    assert leaves == [("seat.depth.value", attributes["seat"]["children"]["depth"]["children"]["value"])]
    assert has_placeholder_source(leaves[0][1])
    assert count_placeholder_leaves(attributes) == 1


def test_ensure_rule_at_path_creates_nested_nodes():
    attributes = {}

    leaf = ensure_rule_at_path(attributes, "frame.material.value")

    assert get_rule_at_path(attributes, "frame.material.value") is leaf
    assert attributes["frame"]["children"]["material"]["children"]["value"] is leaf


def test_replace_placeholder_sources_removes_todo_entries():
    rule = {
        "sources": [
            {"evidence": "TODO: review source mapping for room_type"},
            {"path": "product.attributes.Room Type"},
        ]
    }

    replace_placeholder_sources(
        rule,
        [{"path": "product.attributes.Room Type", "confidence": "high"}],
    )

    assert len(rule["sources"]) == 1
    assert rule["sources"][0]["path"] == "product.attributes.Room Type"
