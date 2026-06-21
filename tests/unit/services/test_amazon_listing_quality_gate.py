"""Unit tests for AmazonListingQualityGate."""
from src.services.amazon_listing_quality_gate import AmazonListingQualityGate


class FakeSchemaService:
    def __init__(self, schema):
        self.schema = schema

    def get_cached_schema(self, product_type):
        return self.schema


def _plan(**attrs):
    attributes = {
        "item_name": [{"value": "36 Inch Bathroom Vanity"}],
        "product_description": [{"value": "Modern bathroom cabinet."}],
        "main_product_image_locator": [{"media_location": "https://img.example/main.jpg"}],
        "item_depth_width_height": [
            {
                "depth": {"value": 20, "unit": "inches"},
                "width": {"value": 36, "unit": "inches"},
                "height": {"value": 34, "unit": "inches"},
            }
        ],
    }
    attributes.update(attrs)
    return {"sku": "SKU1", "product_type": "CABINET", "attributes": attributes}


def test_auto_fills_recommended_use_for_cabinet():
    gate = AmazonListingQualityGate(schema_service=None, marketplace_id="MARKET1")

    result = gate.prepare_plan(_plan())

    assert result["blocked"] is False
    recommended = result["plan"]["attributes"]["recommended_uses_for_product"]
    assert recommended[0]["value"] == "Bathroom"
    assert recommended[0]["marketplace_id"] == "MARKET1"
    assert any(f["code"] == "AUTO_FILLED_RECOMMENDED_USE" for f in result["findings"])


def test_blocks_pesticide_claim_risk():
    gate = AmazonListingQualityGate(schema_service=None)

    result = gate.prepare_plan(
        _plan(product_description=[{"value": "Resists bacteria buildup in humid rooms."}])
    )

    assert result["blocked"] is True
    assert any(f["code"] == "PESTICIDE_CLAIM_RISK" for f in result["findings"])


def test_warns_for_cabinet_width_over_preferred_observed_range():
    gate = AmazonListingQualityGate(schema_service=None)

    result = gate.prepare_plan(
        _plan(
            item_depth_width_height=[
                {
                    "depth": {"value": 22, "unit": "inches"},
                    "width": {"value": 52.76, "unit": "inches"},
                    "height": {"value": 33, "unit": "inches"},
                }
            ]
        )
    )

    assert result["blocked"] is False
    assert any(
        f["code"] == "ISSUE_DERIVED_DIMENSION_RANGE"
        and f["severity"] == "WARNING"
        and f["live_blocking"] is True
        for f in result["findings"]
    )


def test_blocks_missing_main_image():
    gate = AmazonListingQualityGate(schema_service=None)

    result = gate.prepare_plan(_plan(main_product_image_locator=[]))

    assert result["blocked"] is True
    assert any(f["code"] == "MISSING_MAIN_IMAGE" for f in result["findings"])


def test_blocks_item_width_variation_without_item_width_payload():
    gate = AmazonListingQualityGate(schema_service=None)

    result = gate.prepare_plan(
        _plan(
            variation_theme=[{"name": "ITEM_WIDTH"}],
            item_width=[],
        )
    )

    assert result["blocked"] is True
    assert any(
        f["code"] == "MISSING_VARIATION_ITEM_WIDTH"
        for f in result["findings"]
    )


def test_blocks_missing_required_attribute_from_cached_schema():
    gate = AmazonListingQualityGate(
        schema_service=FakeSchemaService(
            {"schema_json": {}, "required_properties": ["brand"]}
        )
    )

    result = gate.prepare_plan(_plan())

    assert result["blocked"] is True
    assert any(
        f["code"] == "MISSING_REQUIRED_ATTRIBUTE"
        and f["attribute_names"] == ["brand"]
        for f in result["findings"]
    )


def test_supplier_image_is_warning_by_default_and_blocking_when_required():
    plan = _plan(
        main_product_image_locator=[
            {"media_location": "https://b2bfiles1.gigab2b.cn/image/main.jpg"}
        ]
    )

    default_result = AmazonListingQualityGate(schema_service=None).prepare_plan(plan)
    strict_result = AmazonListingQualityGate(
        schema_service=None,
        require_reviewed_images=True,
    ).prepare_plan(plan)

    assert default_result["blocked"] is False
    assert strict_result["blocked"] is True
    assert any(
        f["code"] == "SUPPLIER_IMAGE_REVIEW_RECOMMENDED"
        for f in strict_result["findings"]
    )
