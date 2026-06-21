"""Unit tests for API-native Amazon listing draft builder."""

from src.services.amazon_listing_draft_builder import AmazonListingDraftBuilder


def _product_data(**overrides):
    data = {
        "meow_sku": "MEOW1",
        "vendor_sku": "GIGA1",
        "category_name": "CABINET",
        "product_name": "Generated Cabinet Title",
        "product_description": "Generated cabinet description.",
        "selling_point_1": "Feature one",
        "selling_point_2": "Feature two",
        "selling_point_3": "",
        "selling_point_4": None,
        "selling_point_5": "Feature five",
        "raw_data": {
            "name": "Raw Cabinet",
            "mainImageUrl": "https://img.example/main.jpg",
            "imageUrls": ["https://img.example/alt.jpg"],
            "assembledLength": 30,
            "assembledWidth": 20,
            "assembledHeight": 34,
            "weight": 55,
            "attributes": {"Main Color": "White", "Main Material": "MDF"},
            "placeOfOrigin": "China",
        },
        "final_price": 199.99,
        "total_quantity": 12,
    }
    data.update(overrides)
    return data


def test_build_draft_from_product_data_uses_generated_content_and_offer():
    draft = AmazonListingDraftBuilder().build(_product_data(), product_type="CABINET")

    assert draft.sku == "MEOW1"
    assert draft.vendor_sku == "GIGA1"
    assert draft.product_type == "CABINET"
    assert draft.standard_product.sku == "MEOW1"
    assert draft.content.title == "Generated Cabinet Title"
    assert draft.content.bullets == ["Feature one", "Feature two", "Feature five"]
    assert draft.offer.price == 199.99
    assert draft.offer.quantity == 12
    assert draft.source_trace["vendor_source"] == "giga"


def test_build_draft_uses_commercial_gate_publish_quantity_when_present():
    draft = AmazonListingDraftBuilder().build(
        _product_data(
            total_quantity=50,
            source_publish_quantity=50,
            publish_quantity=10,
        ),
        product_type="CABINET",
    )

    assert draft.offer.quantity == 10
    assert draft.source_trace["source_publish_quantity"] == 50
    assert draft.source_trace["publish_quantity"] == 10


def test_build_draft_falls_back_to_raw_content_when_generated_details_missing():
    draft = AmazonListingDraftBuilder().build(
        _product_data(
            product_name="",
            product_description="",
            selling_point_1="",
        ),
        product_type="CABINET",
    )

    assert draft.content.title == "Raw Cabinet"
    assert draft.content.description == ""


def test_build_draft_uses_combo_info_when_main_dimensions_not_applicable():
    draft = AmazonListingDraftBuilder().build(
        _product_data(
            raw_data={
                "name": "Combo Vanity",
                "mainImageUrl": "https://img.example/main.jpg",
                "lengthUnit": "in",
                "weightUnit": "lb",
                "assembledLength": "Not Applicable",
                "assembledWidth": "Not Applicable",
                "assembledHeight": "Not Applicable",
                "assembledWeight": "Not Applicable",
                "comboInfo": [
                    {"qty": 1, "length": 46.06, "width": 20.08, "height": 10.63, "weight": 99},
                    {"qty": 1, "length": 53.54, "width": 24.02, "height": 13, "weight": 61.73},
                ],
            }
        ),
        product_type="CABINET",
    )

    dims = draft.standard_product.dimensions
    assert dims.assembled_length == 53.54
    assert dims.assembled_width == 24.02
    assert dims.assembled_height == 13
    assert dims.assembled_weight == 160.73


def test_build_draft_rejects_missing_sku():
    try:
        AmazonListingDraftBuilder().build(_product_data(meow_sku=""), "CABINET")
    except ValueError as exc:
        assert "meow_sku" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
