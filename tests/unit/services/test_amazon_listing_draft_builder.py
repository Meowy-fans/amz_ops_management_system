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


def test_build_draft_rejects_missing_sku():
    try:
        AmazonListingDraftBuilder().build(_product_data(meow_sku=""), "CABINET")
    except ValueError as exc:
        assert "meow_sku" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
