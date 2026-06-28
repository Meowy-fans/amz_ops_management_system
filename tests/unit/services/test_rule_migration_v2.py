"""Unit tests for V2 rule migration and golden regression helpers."""

import copy

from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.rule_migration_v2 import RuleMigrationV2


def test_live_eligible_migration_preserves_legacy_attributes_only():
    migrator = RuleMigrationV2()
    legacy = {
        "product_type": "SOFA",
        "mode": "live_eligible",
        "attributes": {
            "seat": {"children": {"depth": {"sources": [{"path": "x"}]}}},
            "model_name": {"sources": [{"path": "product.vendor_sku"}]},
        },
    }
    skeleton = {
        "product_type": "SOFA",
        "mode": "dry_run",
        "attributes": {
            "seat": {"children": {"depth": {"sources": [{"default": None}]}}},
            "model_name": {"sources": [{"default": None}]},
            "new_schema_attr": {"sources": [{"default": None}]},
        },
    }

    result = migrator.migrate_rules("SOFA", legacy, skeleton)

    assert result.mode == "live_eligible"
    assert result.rules["attributes"] == legacy["attributes"]
    assert "new_schema_attr" not in result.rules["attributes"]
    assert result.added_attribute_names == []


def test_dry_run_migration_overrides_with_full_legacy_blocks():
    migrator = RuleMigrationV2()
    legacy = {
        "product_type": "TABLE",
        "mode": "dry_run",
        "attributes": {
            "frame": {
                "level": "required",
                "sources": [{"path": "product.attributes.Frame"}],
            }
        },
    }
    skeleton = {
        "product_type": "TABLE",
        "mode": "dry_run",
        "attributes": {
            "frame": {
                "children": {"material": {"sources": [{"default": None}]}},
            },
            "item_shape": {"sources": [{"default": None}]},
        },
    }

    result = migrator.migrate_rules("TABLE", legacy, skeleton)

    assert result.rules["attributes"]["frame"] == legacy["attributes"]["frame"]
    assert "item_shape" in result.rules["attributes"]
    assert result.added_attribute_names == ["item_shape"]


def test_dry_run_migration_prefers_skeleton_children_for_flat_placeholder_blocks():
    migrator = RuleMigrationV2()
    legacy = {
        "product_type": "TABLE",
        "mode": "dry_run",
        "attributes": {
            "item_depth_width_height": {
                "level": "required",
                "shape": "object",
                "sources": [
                    {
                        "default": None,
                        "evidence": "TODO: review source mapping for item_depth_width_height",
                    }
                ],
            },
            "included_components": {
                "level": "required",
                "sources": [{"path": "product.attributes.Included Components"}],
            },
        },
    }
    skeleton = {
        "product_type": "TABLE",
        "mode": "dry_run",
        "dimension_strategy": "item_depth_width_height",
        "attributes": {
            "item_depth_width_height": {
                "shape": "array_object",
                "children": {
                    "depth": {
                        "children": {
                            "value": {"sources": [{"default": None, "evidence": "TODO: x"}]}
                        }
                    }
                },
            },
            "item_weight": {
                "shape": "array_object",
                "children": {
                    "value": {"sources": [{"default": None, "evidence": "TODO: y"}]}
                },
            },
        },
    }

    result = migrator.migrate_rules("TABLE", legacy, skeleton)

    assert result.rules["dimension_strategy"] == "item_depth_width_height"
    assert "depth" in result.rules["attributes"]["item_depth_width_height"]["children"]
    assert result.rules["attributes"]["included_components"]["sources"][0]["path"] == (
        "product.attributes.Included Components"
    )
    assert "item_weight" in result.rules["attributes"]


def test_attribute_differences_detects_changed_values():
    differences = RuleMigrationV2._attribute_differences(
        {"color": [{"value": "Red"}]},
        {"color": [{"value": "Blue"}]},
    )

    assert differences == ["changed_attribute:color"]


def test_attribute_differences_empty_for_identical_payloads():
    payload = {"item_name": [{"value": "Chair", "language_tag": "en_US"}]}

    assert RuleMigrationV2._attribute_differences(payload, copy.deepcopy(payload)) == []
