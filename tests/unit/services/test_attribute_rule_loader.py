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
