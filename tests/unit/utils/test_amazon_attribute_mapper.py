"""Unit tests for AmazonAttributeMapper."""
from src.utils.amazon_attribute_mapper import AmazonAttributeMapper


def _make_row(**overrides):
    row = {
        "SKU": "SKU1",
        "Item Name": "Test Cabinet",
        "Product Description": "A great cabinet.",
        "Bullet Point": ["Feature A", "Feature B"],
        "Your Price USD (Sell on Amazon, US)": 199.99,
        "Quantity (US)": 10,
        "Main Image URL": "https://img.example/1.jpg",
        "Other Image URL": ["https://img.example/2.jpg", "https://img.example/3.jpg"],
        "Brand Name": "TestBrand",
        "Item Type Keyword": "cabinet-thing",
        "Style": "Modern",
        "Color": "White",
        "Country of Origin": "China",
        "Item Weight": 50.5,
        "Item Depth Front To Back": 20.0,
        "Item Width Side To Side": 30.0,
        "Item Height Floor To Top": 34.0,
        "Door Style": "Shaker",
        "Fabric Type": "Wood",
        "Material": "Wood, Glass",
        "Listing Action": "Create",
        "Parentage Level": "Parent",
        "List Price": 249.99,
    }
    row.update(overrides)
    return row


def test_map_rows_to_plans_basic():
    mapper = AmazonAttributeMapper(product_type="CABINET")
    rows = [_make_row()]
    plans = mapper.map_rows_to_plans(rows)

    assert len(plans) == 1
    plan = plans[0]
    assert plan["sku"] == "SKU1"
    assert plan["product_type"] == "CABINET"
    attrs = plan["attributes"]

    assert attrs["item_name"] == [{"value": "Test Cabinet"}]
    assert attrs["product_description"] == [{"value": "A great cabinet."}]
    assert attrs["bullet_point"] == [{"value": "Feature A"}, {"value": "Feature B"}]
    assert "brand" in attrs
    assert "purchasable_offer" in attrs
    price = attrs["purchasable_offer"][0]
    assert price["our_price"][0]["schedule"][0]["value_with_tax"] == 199.99
    assert attrs["fulfillment_availability"][0]["quantity"] == 10
    assert attrs["country_of_origin"] == [{"value": "CN"}]
    assert attrs["item_weight"] == [{"value": 50.5, "unit": "pounds"}]
    # CABINET uses combined item_depth_width_height
    dims = attrs["item_depth_width_height"][0]
    assert dims["depth"]["value"] == 20.0
    assert dims["depth"]["unit"] == "inches"


def test_map_rows_skips_empty_sku():
    mapper = AmazonAttributeMapper(product_type="CABINET")
    rows = [_make_row(SKU="")]
    plans = mapper.map_rows_to_plans(rows)
    assert plans == []


def test_map_rows_skips_skip_type_fields():
    mapper = AmazonAttributeMapper(product_type="CABINET")
    rows = [_make_row()]
    plans = mapper.map_rows_to_plans(rows)
    attrs = plans[0]["attributes"]
    assert "Listing Action" not in str(attrs)
    assert "_listing_action" not in attrs


def test_map_rows_handles_none_values():
    mapper = AmazonAttributeMapper(product_type="CABINET")
    rows = [_make_row(Color=None, Style="")]
    plans = mapper.map_rows_to_plans(rows)
    attrs = plans[0]["attributes"]
    assert "color" not in attrs
    assert "style" not in attrs


def test_map_rows_handles_multiple_rows():
    mapper = AmazonAttributeMapper(product_type="CABINET")
    rows = [_make_row(SKU="A"), _make_row(SKU="B")]
    plans = mapper.map_rows_to_plans(rows)
    assert len(plans) == 2
    assert plans[0]["sku"] == "A"
    assert plans[1]["sku"] == "B"
