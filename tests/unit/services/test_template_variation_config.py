from unittest.mock import MagicMock

from src.services.progress_reporter import NullProgressReporter
from src.services.template_variation_config import (
    DEFAULT_PRIORITY_THEMES,
    determine_priority_themes,
    generate_variation_mapping,
    parse_priority_theme_input,
)


def test_generate_variation_mapping_matches_template_fields_and_theme_parts():
    mapping = generate_variation_mapping(
        template_fields=["SKU", "Color", "Size", "Material"],
        variation_themes=["Color/Size"],
    )

    assert mapping == {
        "color_name": "Color",
        "size_name": "Size",
    }


def test_parse_priority_theme_input_normalizes_values():
    assert parse_priority_theme_input(" Color/Size, style , ") == [
        "COLOR/SIZE",
        "STYLE",
    ]


def test_determine_priority_themes_uses_user_input_first():
    repo = MagicMock()

    themes = determine_priority_themes(
        "CABINET",
        repo,
        NullProgressReporter(),
        input_func=lambda: "color, size",
    )

    assert themes == ["COLOR", "SIZE"]
    repo.find_latest_priority_themes_by_category.assert_not_called()


def test_determine_priority_themes_uses_history_when_input_empty():
    repo = MagicMock()
    repo.find_latest_priority_themes_by_category.return_value = ["MATERIAL"]

    themes = determine_priority_themes(
        "CABINET",
        repo,
        NullProgressReporter(),
        input_func=lambda: "",
    )

    assert themes == ["MATERIAL"]
    repo.find_latest_priority_themes_by_category.assert_called_once_with("CABINET")


def test_determine_priority_themes_falls_back_to_defaults():
    repo = MagicMock()
    repo.find_latest_priority_themes_by_category.return_value = None

    themes = determine_priority_themes(
        "CABINET",
        repo,
        NullProgressReporter(),
        input_func=lambda: "",
    )

    assert themes == DEFAULT_PRIORITY_THEMES
