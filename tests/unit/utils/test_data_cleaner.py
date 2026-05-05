import json

from src.utils.data_cleaner import DataCleaner


def test_deep_clean_recursively_removes_low_priority_fields_and_cleans_text():
    data = {
        "sku": "SKU-1",
        "name": "<b>Cabinet</b>",
        "imageUrls": ["https://example.com/a.jpg"],
        "nested": {
            "description": "<div><img src='x.png'>hidden image block</div>Visible",
            "reviews": ["remove"],
            "items": [
                "<p>Keep</p> https://cdn.example.com/image.webp",
                {"photos": ["remove"], "material": "Wood"},
            ],
        },
    }

    cleaned = DataCleaner.deep_clean(data)

    assert cleaned == {
        "sku": "SKU-1",
        "name": "Cabinet",
        "nested": {
            "description": "Visible",
            "items": ["Keep", {"material": "Wood"}],
        },
    }


def test_deep_clean_returns_non_string_scalars_unchanged():
    assert DataCleaner.deep_clean(12) == 12
    assert DataCleaner.deep_clean(None) is None
    assert DataCleaner.deep_clean(True) is True


def test_clean_text_removes_html_tags_image_blocks_image_urls_and_collapses_whitespace():
    text = """
        <div class="image"><span>prefix</span><img src="a.jpg" />caption</div>
        <p>Hello <strong>World</strong></p>
        https://cdn.example.com/product.PNG extra
    """

    assert DataCleaner.clean_text(text) == "Hello World extra"


def test_clean_text_returns_empty_values_unchanged():
    assert DataCleaner.clean_text("") == ""


def test_smart_truncate_returns_full_json_when_within_limit():
    data = {"sku": "SKU-1", "name": "Cabinet"}

    result = DataCleaner.smart_truncate(data, max_json_length=1000)

    assert json.loads(result) == data


def test_smart_truncate_shortens_long_description_field_before_filtering():
    data = {
        "sku": "SKU-1",
        "longDescription": "x" * 1200,
        "short": "keep",
    }

    result = DataCleaner.smart_truncate(data, max_json_length=1150)
    parsed = json.loads(result)

    assert parsed["sku"] == "SKU-1"
    assert parsed["short"] == "keep"
    assert parsed["longDescription"] == ("x" * 1000) + "..."


def test_smart_truncate_drops_non_priority_long_fields_after_description_truncation():
    data = {
        "sku": "SKU-1",
        "name": "Cabinet",
        "nonessential": "x" * 800,
        "short_note": "keep",
    }

    result = DataCleaner.smart_truncate(data, max_json_length=180)
    parsed = json.loads(result)

    assert parsed == {
        "sku": "SKU-1",
        "name": "Cabinet",
        "short_note": "keep",
    }


def test_smart_truncate_keeps_only_core_fields_when_filtered_payload_still_too_large():
    data = {
        "sku": "SKU-1",
        "name": "Cabinet",
        "brand": "Meow",
        "categoryCode": "CAB001",
        "mainAttributes": {"color": "black"},
        "specifications": {"material": "wood"},
        "price": "9" * 300,
        "material": "wood",
    }

    result = DataCleaner.smart_truncate(data, max_json_length=260)
    parsed = json.loads(result)

    assert parsed == {
        "sku": "SKU-1",
        "name": "Cabinet",
        "brand": "Meow",
        "categoryCode": "CAB001",
        "mainAttributes": {"color": "black"},
        "specifications": {"material": "wood"},
    }


def test_smart_truncate_force_truncates_core_payload_and_marks_original_length():
    data = {
        "sku": "SKU-1",
        "name": "Cabinet",
        "brand": "Meow",
        "categoryCode": "CAB001",
        "mainAttributes": {"description": "x" * 500},
        "specifications": {"detail": "y" * 500},
    }

    result = DataCleaner.smart_truncate(data, max_json_length=180)
    parsed = json.loads(result)

    assert parsed["__truncated__"] is True
    assert parsed["__original_length__"] > len(result)


def test_truncate_data_returns_original_when_within_limit():
    assert DataCleaner.truncate_data("short", max_length=10) == "short"


def test_truncate_data_appends_marker_when_over_limit():
    assert DataCleaner.truncate_data("abcdef", max_length=3) == "abc\n...(已截断)"
