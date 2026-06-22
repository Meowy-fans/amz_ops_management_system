"""Unit tests for API attribute rule loading."""

from pathlib import Path

from src.services.attribute_rule_loader import AttributeRuleLoader


def test_loader_defaults_missing_rule_file_to_dry_run(tmp_path: Path):
    loader = AttributeRuleLoader(config_dir=tmp_path)

    rules = loader.load("SOFA")

    assert rules["product_type"] == "SOFA"
    assert rules["mode"] == "dry_run"
    assert rules["attributes"] == {}
    assert loader.is_live_eligible("SOFA") is False


def test_loader_preserves_explicit_live_eligible_mode_from_config_map():
    loader = AttributeRuleLoader(
        config_by_type={
            "CABINET": {
                "product_type": "CABINET",
                "mode": "live_eligible",
                "attributes": {"room_type": {"level": "recommended"}},
            }
        }
    )

    rules = loader.load("cabinet")

    assert rules["mode"] == "live_eligible"
    assert loader.mode("CABINET") == "live_eligible"
    assert loader.is_live_eligible("CABINET") is True


def test_loader_merges_presets_before_product_rules():
    loader = AttributeRuleLoader(
        config_by_type={
            "CHAIR": {
                "product_type": "CHAIR",
                "presets": ["amazon_universal_required_v1"],
                "attributes": {
                    "brand": {
                        "level": "required",
                        "sources": [{"default": "Custom"}],
                    },
                    "seat_depth": {"level": "recommended"},
                },
            }
        },
        preset_by_name={
            "amazon_universal_required_v1": {
                "attributes": {
                    "brand": {
                        "level": "required",
                        "sources": [{"default": "Generic"}],
                    },
                    "item_name": {
                        "level": "required",
                        "sources": [{"path": "content.title"}],
                    },
                }
            }
        },
    )

    rules = loader.load("CHAIR")

    assert rules["attributes"]["brand"]["sources"] == [{"default": "Custom"}]
    assert rules["attributes"]["item_name"]["sources"] == [
        {"path": "content.title"}
    ]
    assert rules["attributes"]["seat_depth"]["level"] == "recommended"


def test_loader_can_read_named_preset_without_product_merge():
    loader = AttributeRuleLoader(
        preset_by_name={
            "amazon_required_safe_defaults_v1": {
                "attributes": {
                    "number_of_items": {
                        "sources": [
                            {
                                "default": 1,
                                "confidence": "medium",
                                "evidence": "Single item fallback.",
                                "safe_default": True,
                            }
                        ]
                    }
                }
            }
        }
    )

    preset = loader.load_preset("amazon_required_safe_defaults_v1")

    assert preset["attributes"]["number_of_items"]["sources"][0]["safe_default"] is True
