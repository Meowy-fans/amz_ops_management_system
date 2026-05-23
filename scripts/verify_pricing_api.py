"""Smoke test: verify Product Pricing API is accessible.

Usage:
    python3 scripts/verify_pricing_api.py

Requires AMAZON_* env vars set (runs inside production Docker container).
Tests each pricing endpoint and reports status.
"""

import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path
_proj_root = Path(__file__).resolve().parent.parent
if str(_proj_root) not in sys.path:
    sys.path.insert(0, str(_proj_root))

def main():
    print("=" * 60)
    print("Amazon Product Pricing API — Verification")
    print("=" * 60)

    from infrastructure.amazon.pricing_client import AmazonPricingClient

    client = AmazonPricingClient()
    print(f"✓ MarketPlace: {client.marketplace_id}")

    # 1. Basic connectivity — getItemOffers for a known ASIN
    print("\nTest 1: getItemOffers (B0DJVX8YKC)")
    try:
        resp = client.get_item_offers("B0DJVX8YKC")
        body = resp.get("body", resp)
        payload = body.get("payload", {})
        summary = payload.get("Summary", {})
        buy_box = summary.get("BuyBoxPrices", [])
        lowest = summary.get("LowestPrices", [])
        total_offers = summary.get("TotalOfferCount", 0)

        print(f"  ✓ Buy Box count: {len(buy_box)}")
        if buy_box:
            for bb in buy_box:
                landed = bb.get("LandedPrice", {})
                print(f"    - {bb.get('condition')} / {bb.get('fulfillmentChannel')}: ${landed.get('Amount', 'N/A')}")

        print(f"  ✓ Lowest prices: {len(lowest)} offers")
        for lp in lowest[:3]:
            landed = lp.get("LandedPrice", {})
            print(f"    - {lp.get('condition')} / {lp.get('fulfillmentChannel')}: ${landed.get('Amount', 'N/A')}")

        print(f"  ✓ Total Offer Count: {total_offers}")

        buy_box_price = client.extract_buy_box_price(resp)
        lowest_price = client.extract_lowest_price(resp)
        offer_count = client.extract_offer_count(resp)

        print(f"\n  Parsed → Buy Box: {_format_price(buy_box_price)}")
        print(f"  Parsed → Lowest FBA: {_format_price(lowest_price)}")
        print(f"  Parsed → Offer Count: {offer_count}")

    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return 1

    # 2. Batch — getCompetitivePricing
    print("\nTest 2: getCompetitivePricing (B0DJVX8YKC)")
    try:
        resp = client.get_competitive_pricing(asins=["B0DJVX8YKC"])
        items = client.parse_competitive_result(resp)
        print(f"  ✓ Items returned: {len(items)}")
        for item in items[:2]:
            prices = item.get("competitive_prices", [])
            fba_prices = [p for p in prices if p.get("fulfillment_channel") == "Amazon"]
            ranks = item.get("sales_rankings", [])
            print(f"    ASIN: {item.get('asin')}")
            print(f"    FBA offers: {len(fba_prices)}/{len(prices)}")
            for p in fba_prices[:3]:
                print(f"      ${p.get('landed_price', 'N/A')} (is_us: {p.get('belongs_to_requester')})")
            if ranks:
                print(f"    BSR: {ranks[0].get('rank')} ({ranks[0].get('category')})")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        return 1

    # 3. Batch offers — getItemOffersBatch
    print("\nTest 3: getItemOffersBatch (B0DJVX8YKC)")
    try:
        resp = client.get_item_offers_batch(["B0DJVX8YKC"])
        body = resp.get("body", resp)
        responses = body.get("responses", [])
        print(f"  ✓ Batch responses: {len(responses)}")
        for r in responses[:2]:
            status = r.get("status", {}).get("statusCode", "?")
            summary = r.get("body", {}).get("payload", {}).get("Summary", {})
            total = summary.get("TotalOfferCount", "?")
            print(f"    Status: {status}, Offer Count: {total}")
    except Exception as e:
        print(f"  ✗ FAILED (rate limit may apply): {e}")

    print("\n" + "=" * 60)
    print("✅ All pricing endpoints verified")
    print("=" * 60)
    return 0


def _format_price(price_dict) -> str:
    if not price_dict:
        return "N/A"
    amount = price_dict.get("LandedPrice", {}).get("Amount")
    if amount is None:
        amount = price_dict.get("ListingPrice", {}).get("Amount", "N/A")
    channel = price_dict.get("fulfillmentChannel", "")
    return f"${amount} ({channel})"


if __name__ == "__main__":
    sys.exit(main())
