import pytest

from src.utils.pricing_config import PricingConfigLoader


@pytest.fixture(autouse=True)
def reset_pricing_config_loader():
    original_config = PricingConfigLoader._config
    original_path = PricingConfigLoader._config_path
    PricingConfigLoader._config = None
    yield
    PricingConfigLoader._config = original_config
    PricingConfigLoader._config_path = original_path


def test_load_config_reads_yaml_and_caches_result(tmp_path, monkeypatch):
    config_path = tmp_path / "pricing.yaml"
    config_path.write_text(
        """
fallback:
  margin_rate: 0.30
categories:
  cabinet:
    margin_rate: 0.42
""",
        encoding="utf-8",
    )
    PricingConfigLoader._config_path = str(config_path)
    open_calls = []
    original_open = open

    def record_open(*args, **kwargs):
        open_calls.append(args[0])
        return original_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", record_open)

    first = PricingConfigLoader._load_config()
    second = PricingConfigLoader._load_config()

    assert first == {
        "fallback": {"margin_rate": 0.30},
        "categories": {"cabinet": {"margin_rate": 0.42}},
    }
    assert second is first
    assert open_calls == [str(config_path)]


def test_load_config_reraises_missing_file(tmp_path):
    PricingConfigLoader._config_path = str(tmp_path / "missing.yaml")

    with pytest.raises(FileNotFoundError):
        PricingConfigLoader._load_config()


def test_load_config_reraises_invalid_yaml(tmp_path):
    config_path = tmp_path / "pricing.yaml"
    config_path.write_text("fallback: [unterminated", encoding="utf-8")
    PricingConfigLoader._config_path = str(config_path)

    with pytest.raises(Exception):
        PricingConfigLoader._load_config()


def test_get_params_for_category_returns_fallback_when_category_missing(tmp_path):
    config_path = tmp_path / "pricing.yaml"
    config_path.write_text(
        """
fallback:
  margin_rate: 0.30
  min_profit: 20
categories:
  cabinet:
    margin_rate: 0.42
""",
        encoding="utf-8",
    )
    PricingConfigLoader._config_path = str(config_path)

    assert PricingConfigLoader.get_params_for_category(None) == {
        "margin_rate": 0.30,
        "min_profit": 20,
    }
    assert PricingConfigLoader.get_params_for_category("") == {
        "margin_rate": 0.30,
        "min_profit": 20,
    }
    assert PricingConfigLoader.get_params_for_category("unknown") == {
        "margin_rate": 0.30,
        "min_profit": 20,
    }


def test_get_params_for_category_merges_lowercase_category_over_fallback(tmp_path):
    config_path = tmp_path / "pricing.yaml"
    config_path.write_text(
        """
fallback:
  margin_rate: 0.30
  min_profit: 20
  shipping_buffer: 8
categories:
  cabinet:
    margin_rate: 0.42
    oversize_fee: 15
""",
        encoding="utf-8",
    )
    PricingConfigLoader._config_path = str(config_path)

    assert PricingConfigLoader.get_params_for_category("CABINET") == {
        "margin_rate": 0.42,
        "min_profit": 20,
        "shipping_buffer": 8,
        "oversize_fee": 15,
    }


def test_get_params_for_category_handles_missing_config_sections(tmp_path):
    config_path = tmp_path / "pricing.yaml"
    config_path.write_text("{}", encoding="utf-8")
    PricingConfigLoader._config_path = str(config_path)

    assert PricingConfigLoader.get_params_for_category("CABINET") == {}
