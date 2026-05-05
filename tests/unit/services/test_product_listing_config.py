import json
from pathlib import Path

from src.services.product_listing_config import (
    find_default_category_config_path,
    load_category_config,
)


def test_find_default_category_config_path_walks_up_to_config_file(tmp_path):
    project_root = tmp_path / "project"
    module_dir = project_root / "src" / "services"
    config_dir = project_root / "config" / "amz_listing_data_mapping"
    module_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    start_file = module_dir / "product_listing_service.py"
    start_file.write_text("# module", encoding="utf-8")
    config_file = config_dir / "category_mapping.json"
    config_file.write_text('{"category_details": {}}', encoding="utf-8")

    assert find_default_category_config_path(str(start_file)) == config_file


def test_find_default_category_config_path_returns_none_when_missing(tmp_path):
    module_file = tmp_path / "src" / "services" / "product_listing_service.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("# module", encoding="utf-8")

    assert find_default_category_config_path(str(module_file)) is None


def test_find_default_category_config_path_returns_none_for_invalid_start_file():
    assert find_default_category_config_path("\0invalid") is None


def test_load_category_config_reads_explicit_category_details(tmp_path):
    config_path = tmp_path / "category_mapping.json"
    config = {
        "category_details": {
            "CABINET": {
                "template": "cabinet.xlsx",
                "output": "cabinet-output",
            }
        },
        "other_key": "ignored",
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")

    assert load_category_config(config_path, __file__) == config["category_details"]


def test_load_category_config_defaults_missing_category_details_to_empty_dict(
    tmp_path,
):
    config_path = tmp_path / "category_mapping.json"
    config_path.write_text("{}", encoding="utf-8")

    assert load_category_config(config_path, __file__) == {}


def test_load_category_config_discovers_default_path_from_start_file(tmp_path):
    project_root = tmp_path / "project"
    module_dir = project_root / "src" / "services"
    config_dir = project_root / "config" / "amz_listing_data_mapping"
    module_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    start_file = module_dir / "product_listing_service.py"
    start_file.write_text("# module", encoding="utf-8")
    config_path = config_dir / "category_mapping.json"
    config_path.write_text(
        json.dumps({"category_details": {"HOME_MIRROR": {"template": "mirror.xlsx"}}}),
        encoding="utf-8",
    )

    assert load_category_config(None, str(start_file)) == {
        "HOME_MIRROR": {"template": "mirror.xlsx"}
    }


def test_load_category_config_returns_none_when_file_missing(tmp_path):
    missing_path = Path(tmp_path / "missing.json")

    assert load_category_config(missing_path, __file__) is None


def test_load_category_config_returns_none_for_invalid_json(tmp_path):
    config_path = tmp_path / "category_mapping.json"
    config_path.write_text("{invalid-json", encoding="utf-8")

    assert load_category_config(config_path, __file__) is None
