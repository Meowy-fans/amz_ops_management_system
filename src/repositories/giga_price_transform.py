"""Pure data transforms for Giga product price persistence."""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime strings returned by Giga."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def filter_valid_prices(prices: List[Dict]) -> Tuple[List[Dict], int]:
    """Keep records with a price or available SKU flag."""
    valid_prices = []
    invalid_count = 0

    for item in prices:
        price = item.get("price")
        sku_available = item.get("skuAvailable", False)

        if price is not None or sku_available:
            valid_prices.append(item)
        else:
            invalid_count += 1
            logger.debug(
                f"过滤无效价格: SKU={item.get('sku')}, "
                "price=None, available=False"
            )

    return valid_prices, invalid_count


def deduplicate_prices_by_giga_index(prices: List[Dict]) -> List[Dict]:
    """Deduplicate price records by SKU, keeping the highest Giga index."""
    sku_map = {}

    for item in prices:
        sku = item.get("sku")
        if not sku:
            continue

        if sku in sku_map:
            existing_giga_index = float(
                sku_map[sku].get("sellerInfo", {}).get("gigaIndex", 0)
            )
            current_giga_index = float(
                item.get("sellerInfo", {}).get("gigaIndex", 0)
            )

            if current_giga_index > existing_giga_index:
                logger.debug(
                    f"SKU {sku}: 替换供应商 "
                    f"(Giga指数 {existing_giga_index} → {current_giga_index})"
                )
                sku_map[sku] = item
        else:
            sku_map[sku] = item

    return list(sku_map.values())


def build_base_price_row(item: Dict) -> Dict:
    """Build a database row for the base price table."""
    shipping_fee_range = item.get("shippingFeeRange", {})
    seller_info = item.get("sellerInfo", {})

    return {
        "giga_sku": item.get("sku"),
        "currency": item.get("currency") or "USD",
        "base_price": item.get("price"),
        "shipping_fee": item.get("shippingFee"),
        "shipping_fee_min": shipping_fee_range.get("minAmount"),
        "shipping_fee_max": shipping_fee_range.get("maxAmount"),
        "exclusive_price": item.get("exclusivePrice"),
        "discounted_price": item.get("discountedPrice"),
        "promotion_start": parse_datetime(item.get("promotionFrom")),
        "promotion_end": parse_datetime(item.get("promotionTo")),
        "map_price": item.get("mapPrice"),
        "future_map_price": item.get("futureMapPrice"),
        "effect_map_time": parse_datetime(item.get("effectMapTime")),
        "sku_available": item.get("skuAvailable", False),
        "seller_info": json.dumps(seller_info),
        "full_response": json.dumps(item),
    }


def build_tier_price_rows(item: Dict) -> List[Dict]:
    """Build database rows for all tier price fields on one Giga item."""
    sku = item.get("sku")
    rows = []
    tier_mapping = [
        ("spot", item.get("spotPrice", [])),
        ("margin", item.get("marginPrice", [])),
        ("rebate", item.get("rebatesPrice", [])),
        ("future", item.get("futurePrice", [])),
    ]

    for tier_type, tier_prices in tier_mapping:
        if not tier_prices:
            continue

        for price_info in tier_prices:
            rows.append({
                "giga_sku": sku,
                "tier_type": tier_type,
                "min_quantity": price_info.get("minQuantity"),
                "max_quantity": price_info.get("maxQuantity"),
                "price": price_info.get("price"),
                "discounted_price": price_info.get("discountedSpotPrice")
                or price_info.get("discountedPrice"),
                "effective_date": parse_datetime(price_info.get("effectiveDate")),
            })

    return rows


def prepare_price_rows(prices: List[Dict]) -> Tuple[List[Dict], List[Dict], int, List[str]]:
    """Filter, deduplicate, and transform Giga price payloads for persistence."""
    valid_prices, invalid_count = filter_valid_prices(prices)
    if invalid_count > 0:
        logger.info(
            f"过滤无效价格: {len(prices)} → {len(valid_prices)} "
            f"(移除{invalid_count}条)"
        )

    unique_prices = deduplicate_prices_by_giga_index(valid_prices)
    if len(unique_prices) < len(valid_prices):
        logger.info(
            f"去重: {len(valid_prices)} → {len(unique_prices)} "
            f"(合并{len(valid_prices) - len(unique_prices)}条重复)"
        )

    success_count = 0
    failed_skus = []
    base_price_data = []
    tier_price_data = []

    for item in unique_prices:
        try:
            sku = item.get("sku")
            if not sku:
                failed_skus.append("UNKNOWN_SKU")
                continue

            base_price_data.append(build_base_price_row(item))
            tier_price_data.extend(build_tier_price_rows(item))
            success_count += 1
        except Exception as exc:
            logger.error(f"准备SKU {item.get('sku')} 数据失败: {exc}")
            failed_skus.append(item.get("sku", "UNKNOWN"))

    return base_price_data, tier_price_data, success_count, failed_skus
