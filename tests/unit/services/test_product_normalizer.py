"""Unit tests for GigaProductNormalizer."""
from src.models.product import DimensionSpec, StandardProduct
from src.services.product_normalizer import (
    GigaProductNormalizer,
    NORMALIZER_REGISTRY,
    get_normalizer,
)


def _make_giga_raw():
    """Return a minimal but realistic Giga product raw_data dict."""
    return {
        "mpn": "TEST-MPN-001",
        "sku": "GIGA-SKU-001",
        "name": "30 inch Bathroom Vanity Cabinet - White",
        "description": "<div>Premium vanity with ceramic sink.</div>",
        "width": 22.0,
        "height": 20.0,
        "length": 34.0,
        "weight": 95.0,
        "widthCm": 55.88,
        "heightCm": 50.80,
        "lengthCm": 86.36,
        "weightKg": 43.09,
        "lengthUnit": "in",
        "weightUnit": "lb",
        "assembledLength": "30.00",
        "assembledWidth": "18.50",
        "assembledHeight": "34.40",
        "assembledWeight": "101.41",
        "mainImageUrl": "https://cdn.example/main.jpg",
        "imageUrls": [
            "https://cdn.example/main.jpg",
            "https://cdn.example/alt1.jpg",
            "https://cdn.example/alt2.jpg",
        ],
        "videoUrls": ["https://video.example/demo.mp4"],
        "fileUrls": ["https://files.example/manual.pdf"],
        "category": "Bathroom Vanities",
        "categoryCode": 10143,
        "placeOfOrigin": "China",
        "attributes": {
            "Main Color": "White",
            "Main Material": "Ceramic + Plywood",
            "Product Style": "Modern",
            "Use Case": "Bathroom",
        },
        "characteristics": [
            "Premium ceramic sink with high-gloss finish",
            "Solid wood frame with MDF panels for durability",
            "Soft-close hinges and drawer slides",
            "Easy wall-mounted installation",
        ],
        "sellerInfo": {
            "sellerStore": "Test Brand Co",
            "sellerCode": "W9999",
            "sellerType": "GENERAL",
        },
        "associateProductList": ["GIGA-SKU-002", "GIGA-SKU-003"],
        "lithiumBatteryContained": "No",
        "customized": "No",
        "comboFlag": False,
        "comboInfo": [],
        "whiteLabel": "No",
        "toBePublished": True,
        "newArrivalFlag": False,
        "partFlag": False,
        "upc": "",
    }


def _make_price_data():
    return {"base_price": 150.00, "shipping_fee": 25.00, "currency": "USD"}


# ── basic mapping ─────────────────────────────────────────────────

def test_normalize_basic_fields():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), vendor_sku="GIGA-SKU-001", meow_sku="MEOW-001")

    assert product.sku == "MEOW-001"
    assert product.vendor_sku == "GIGA-SKU-001"
    assert product.vendor_source == "giga"
    assert "30 inch Bathroom Vanity" in product.name
    assert "ceramic sink" in product.description.lower()
    assert product.category_hint == "Bathroom Vanities"


def test_normalize_images_main_first():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), "GIGA-SKU-001")

    assert len(product.images) == 3
    assert "main.jpg" in product.images[0]  # main image first
    assert product.images[1:] == [
        "https://cdn.example/alt1.jpg",
        "https://cdn.example/alt2.jpg",
    ]


def test_normalize_bullet_points():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), "GIGA-SKU-001")

    assert len(product.bullet_points) == 4
    assert "ceramic sink" in product.bullet_points[0]


def test_normalize_attributes():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), "GIGA-SKU-001")

    assert product.attributes["Main Color"] == "White"
    assert product.attributes["Main Material"] == "Ceramic + Plywood"
    assert product.attributes["mpn"] == "TEST-MPN-001"
    assert product.attributes["place_of_origin"] == "China"
    assert product.attributes["seller_name"] == "Test Brand Co"


def test_normalize_dimensions_inches():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), "GIGA-SKU-001")

    dims = product.dimensions
    assert dims is not None
    assert dims.length == 34.0
    assert dims.width == 22.0
    assert dims.height == 20.0
    assert dims.weight == 95.0
    assert dims.assembled_length == 30.0
    assert dims.assembled_width == 18.5
    assert dims.assembled_height == 34.4
    assert dims.assembled_weight == 101.41
    assert dims.source_unit == "in"


def test_normalize_dimensions_metric_conversion():
    raw = _make_giga_raw()
    raw["lengthUnit"] = "cm"
    raw["weightUnit"] = "kg"
    raw["length"] = 86.36
    raw["width"] = 55.88
    raw["height"] = 50.80
    raw["weight"] = 43.09

    n = GigaProductNormalizer()
    product = n.normalize(raw, "GIGA-SKU-001")

    dims = product.dimensions
    assert dims is not None
    # 86.36cm / 2.54 ≈ 34.0 inches
    assert abs(dims.length - 34.0) < 0.1
    assert abs(dims.width - 22.0) < 0.1
    # 43.09kg * 2.20462 ≈ 95.0 lb
    assert abs(dims.weight - 95.0) < 0.2
    assert dims.source_unit == "cm"


def test_normalize_combo_dimensions():
    raw = _make_giga_raw()
    raw["comboInfo"] = [{"length": 40, "width": 25, "height": 22}]
    raw["lengthUnit"] = "in"

    n = GigaProductNormalizer()
    product = n.normalize(raw, "GIGA-SKU-001")

    assert product.dimensions_package is not None
    assert product.dimensions_package.length == 40.0
    assert product.dimensions_package.width == 25.0
    assert product.dimensions_package.height == 22.0


def test_normalize_price():
    n = GigaProductNormalizer()
    product = n.normalize(
        _make_giga_raw(), "GIGA-SKU-001", price_data=_make_price_data()
    )

    assert product.price is not None
    assert product.price.cost == 150.0
    assert product.price.shipping_fee == 25.0
    assert product.price.currency == "USD"


def test_normalize_inventory():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), "GIGA-SKU-001", inventory_qty=12)

    assert product.inventory is not None
    assert product.inventory.quantity == 12


def test_normalize_variant_associations():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), "GIGA-SKU-001")

    assert product.variant_associations == ["GIGA-SKU-002", "GIGA-SKU-003"]


def test_normalize_flags():
    raw = _make_giga_raw()
    n = GigaProductNormalizer()

    product = n.normalize(raw, "GIGA-SKU-001", is_oversize=False)
    assert not product.is_oversize
    assert not product.contains_battery

    raw["lithiumBatteryContained"] = "Yes"
    product2 = n.normalize(raw, "GIGA-SKU-001", is_oversize=True)
    assert product2.contains_battery
    assert product2.is_oversize


def test_normalize_no_price_or_inventory():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), "GIGA-SKU-001")

    assert product.price is None
    assert product.inventory is not None
    assert product.inventory.quantity == 0


def test_normalize_videos_and_documents():
    n = GigaProductNormalizer()
    product = n.normalize(_make_giga_raw(), "GIGA-SKU-001")

    assert len(product.videos) == 1
    assert "demo.mp4" in product.videos[0]
    assert len(product.documents) == 1
    assert "manual.pdf" in product.documents[0]


# ── registry ────────────────────────────────────────────────────────

def test_registry_contains_giga():
    assert "giga" in NORMALIZER_REGISTRY
    assert NORMALIZER_REGISTRY["giga"] is GigaProductNormalizer


def test_get_normalizer_returns_instance():
    n = get_normalizer("giga")
    assert isinstance(n, GigaProductNormalizer)


def test_get_normalizer_unknown_raises():
    try:
        get_normalizer("nonexistent")
        assert False, "should raise"
    except ValueError as e:
        assert "nonexistent" in str(e)
