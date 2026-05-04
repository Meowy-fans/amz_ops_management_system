import json

from src.services.variation_theme_helpers import (
    build_correction_prompt,
    build_first_round_prompt,
    check_attribute_uniqueness,
    clean_family_products,
    filter_priority_themes,
    format_variation_attributes,
    strip_html,
)


def test_clean_family_products_strips_html_and_removes_empty_dimensions():
    products = clean_family_products([
        {
            "meow_sku": "SKU1",
            "product_name": "Mirror",
            "product_description": "<p>Nice<br> mirror</p>",
            "raw_data": {
                "attributes": {"color": "white"},
                "assembledHeight": 19.6,
                "assembledWidth": None,
            },
        }
    ])

    assert products == [
        {
            "meow_sku": "SKU1",
            "name": "Mirror",
            "description": "Nice mirror",
            "attributes": {"color": "white"},
            "dimensions_and_weight": {"assembledHeight": 19.6},
        }
    ]
    assert strip_html("") == ""


def test_build_prompts_filter_priority_themes_and_include_products():
    family_data = [{"meow_sku": "SKU1", "raw_data": {"description": "Raw desc"}}]

    first_prompt = json.loads(
        build_first_round_prompt(
            family_data,
            valid_themes=["Color", "Size"],
            priority_themes=["Color", "Invalid"],
        )
    )
    correction_prompt = json.loads(
        build_correction_prompt(
            family_data,
            valid_themes=["Color", "Size"],
            priority_themes=["Size", "Invalid"],
            failed_theme="Color",
        )
    )

    assert filter_priority_themes(["Color", "Bad"], ["Color"]) == ["Color"]
    assert first_prompt["high_priority_themes"] == ["Color"]
    assert first_prompt["products"][0]["description"] == "Raw desc"
    assert correction_prompt["failed_theme"] == "Color"
    assert correction_prompt["recommended_themes"] == ["Size"]


def test_uniqueness_and_formatting_helpers_keep_existing_behavior():
    assert check_attribute_uniqueness({
        "SKU1": {"color_name": "White"},
        "SKU2": {"color_name": "White"},
    }) is False
    assert check_attribute_uniqueness({
        "SKU1": {"color_name": "White"},
        "SKU2": {"color_name": "Black"},
    }) is True

    assert format_variation_attributes({
        "SKU1": {"size_name": "19.6", "color_name": "White"},
        "SKU2": {"size_name": "bad"},
    }) == {
        "SKU1": {"size_name": "20", "color_name": "White"},
        "SKU2": {"size_name": "bad"},
    }
