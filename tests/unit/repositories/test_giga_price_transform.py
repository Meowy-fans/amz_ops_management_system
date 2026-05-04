import json

from src.repositories.giga_price_transform import (
    build_base_price_row,
    build_tier_price_rows,
    deduplicate_prices_by_giga_index,
    filter_valid_prices,
    parse_datetime,
    prepare_price_rows,
)


def test_filter_valid_prices_keeps_price_or_available_records():
    valid, invalid_count = filter_valid_prices([
        {"sku": "A", "price": None, "skuAvailable": False},
        {"sku": "B", "price": 10, "skuAvailable": False},
        {"sku": "C", "price": None, "skuAvailable": True},
    ])

    assert [item["sku"] for item in valid] == ["B", "C"]
    assert invalid_count == 1


def test_deduplicate_prices_by_giga_index_keeps_highest_index():
    result = deduplicate_prices_by_giga_index([
        {"sku": "A", "sellerInfo": {"gigaIndex": "2"}},
        {"sku": "A", "sellerInfo": {"gigaIndex": "5"}},
        {"sku": "B", "sellerInfo": {"gigaIndex": "1"}},
        {"sellerInfo": {"gigaIndex": "9"}},
    ])

    assert result == [
        {"sku": "A", "sellerInfo": {"gigaIndex": "5"}},
        {"sku": "B", "sellerInfo": {"gigaIndex": "1"}},
    ]


def test_build_base_and_tier_rows_parse_dates_and_json_fields():
    item = {
        "sku": "SKU1",
        "price": 12.5,
        "shippingFeeRange": {"minAmount": 1, "maxAmount": 3},
        "sellerInfo": {"gigaIndex": "7"},
        "promotionFrom": "2026-01-01T00:00:00Z",
        "spotPrice": [
            {
                "minQuantity": 1,
                "maxQuantity": 5,
                "price": 10,
                "discountedSpotPrice": 9,
                "effectiveDate": "bad-date",
            }
        ],
    }

    base_row = build_base_price_row(item)
    tier_rows = build_tier_price_rows(item)

    assert base_row["giga_sku"] == "SKU1"
    assert base_row["currency"] == "USD"
    assert base_row["shipping_fee_min"] == 1
    assert base_row["promotion_start"] == parse_datetime("2026-01-01T00:00:00Z")
    assert json.loads(base_row["seller_info"]) == {"gigaIndex": "7"}
    assert tier_rows == [{
        "giga_sku": "SKU1",
        "tier_type": "spot",
        "min_quantity": 1,
        "max_quantity": 5,
        "price": 10,
        "discounted_price": 9,
        "effective_date": None,
    }]


def test_prepare_price_rows_filters_deduplicates_and_tracks_missing_sku():
    base_rows, tier_rows, success_count, failed_skus = prepare_price_rows([
        {"sku": "A", "price": None, "skuAvailable": False},
        {"sku": "B", "price": 10, "sellerInfo": {"gigaIndex": "1"}},
        {"sku": "B", "price": 11, "sellerInfo": {"gigaIndex": "2"}},
        {"price": 9, "sellerInfo": {"gigaIndex": "3"}},
    ])

    assert [row["giga_sku"] for row in base_rows] == ["B"]
    assert base_rows[0]["base_price"] == 11
    assert tier_rows == []
    assert success_count == 1
    assert failed_skus == []
