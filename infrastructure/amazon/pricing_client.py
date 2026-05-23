"""Amazon Product Pricing API client (v0).

Provides competitive pricing, offer details, and Buy Box data.
"""

import logging
from typing import Any, Dict, List, Optional

from infrastructure.amazon.api_client import AmazonAPIClient
from infrastructure.amazon.config import AmazonConfig

logger = logging.getLogger(__name__)


class AmazonPricingClient:
    """Queries Amazon Product Pricing API for competitive intelligence.

    Endpoints:
      - getCompetitivePricing: batch competitive price + sales rank (up to 20 ASINs)
      - getItemOffers: all offers for a single ASIN
      - getItemOffersBatch: offers for up to 20 ASINs (low rate limit: 0.1 req/s)
      - getListingOffers: offers for own listing by SKU
      - getListingOffersBatch: offers for up to 20 SKUs
    """

    _PRICING_PATH = "/products/pricing/v0"

    def __init__(
        self,
        api_client: Optional[AmazonAPIClient] = None,
        marketplace_id: Optional[str] = None,
    ):
        self.api_client = api_client or AmazonAPIClient()
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID

    # ── competitive pricing ─────────────────────────────────────────

    def get_competitive_pricing(
        self,
        asins: Optional[List[str]] = None,
        skus: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get competitive pricing for up to 20 ASINs or SKUs.

        Returns per-ASIN: CompetitivePrices[], NumberOfOfferListings[], SalesRankings[].
        Rate: 0.5 req/s, burst 1.
        """
        if not asins and not skus:
            raise ValueError("Either asins or skus must be provided")
        path = f"{self._PRICING_PATH}/competitivePrice"
        params: Dict[str, Any] = {
            "MarketplaceId": self.marketplace_id,
            "ItemType": "Asin" if asins else "Sku",
        }
        param_key = "Asins" if asins else "Skus"
        identifiers = asins if asins else skus
        if len(identifiers) > 20:
            identifiers = identifiers[:20]
            logger.warning("Truncated %s list to 20 items", param_key.lower())
        params[param_key] = ",".join(identifiers)

        logger.info(
            "getCompetitivePricing: %d items type=%s", len(identifiers), param_key
        )
        return self.api_client.request("GET", path, params=params)

    # ── item offers ─────────────────────────────────────────────────

    def get_item_offers(
        self,
        asin: str,
        customer_type: str = "Consumer",
    ) -> Dict[str, Any]:
        """Get all offers for a single ASIN.

        Returns: LowestPrices[], BuyBoxPrices[], NumberOfOffers[],
        BuyBoxEligibleOffers[], OffersAvailableTime.
        Rate: 5 req/s, burst 10.
        """
        path = f"{self._PRICING_PATH}/items/{asin}/offers"
        params = {
            "MarketplaceId": self.marketplace_id,
            "CustomerType": customer_type,
            "ItemCondition": "New",
        }
        logger.info("getItemOffers: %s", asin)
        return self.api_client.request("GET", path, params=params)

    def get_item_offers_batch(
        self,
        asins: List[str],
        customer_type: str = "Consumer",
    ) -> Dict[str, Any]:
        """Batch query offers for up to 20 ASINs.

        Rate: 0.1 req/s (very low!). Use sparingly.
        """
        if len(asins) > 20:
            asins = asins[:20]
        path = f"{self._PRICING_PATH}/batch/item/offers"
        params: Dict[str, Any] = {
            "MarketplaceId": self.marketplace_id,
            "CustomerType": customer_type,
            "ItemCondition": "New",
        }
        body: Dict[str, List[str]] = {"GetItemOffersBatchRequests": []}
        for asin in asins:
            body["GetItemOffersBatchRequests"].append({"uri": f"/products/pricing/v0/items/{asin}/offers"})

        logger.info("getItemOffersBatch: %d items", len(asins))
        return self.api_client.request("POST", path, params=params, json=body)

    # ── listing offers (own SKU) ────────────────────────────────────

    def get_listing_offers(
        self,
        sku: str,
        customer_type: str = "Consumer",
    ) -> Dict[str, Any]:
        """Get offers for your own listing by SKU."""
        path = f"{self._PRICING_PATH}/listings/{sku}/offers"
        params = {
            "MarketplaceId": self.marketplace_id,
            "CustomerType": customer_type,
            "ItemCondition": "New",
        }
        logger.info("getListingOffers: %s", sku)
        return self.api_client.request("GET", path, params=params)

    def get_listing_offers_batch(
        self,
        skus: List[str],
        customer_type: str = "Consumer",
    ) -> Dict[str, Any]:
        """Batch query offers for up to 20 of your own SKUs."""
        if len(skus) > 20:
            skus = skus[:20]
        path = f"{self._PRICING_PATH}/batch/listing/offers"
        params: Dict[str, Any] = {
            "MarketplaceId": self.marketplace_id,
            "CustomerType": customer_type,
            "ItemCondition": "New",
        }
        body: Dict[str, List[str]] = {"GetListingOffersBatchRequests": []}
        for sku in skus:
            body["GetListingOffersBatchRequests"].append({"uri": f"/products/pricing/v0/listings/{sku}/offers"})

        logger.info("getListingOffersBatch: %d items", len(skus))
        return self.api_client.request("POST", path, params=params, json=body)

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def extract_lowest_price(offers_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract the lowest FBA price from a get_item_offers response."""
        body = offers_result.get("body") or offers_result
        payload = body.get("payload") or {}
        summary = payload.get("Summary") or {}
        prices = summary.get("LowestPrices") or []
        for price in prices:
            if price.get("fulfillmentChannel") == "Amazon" and price.get("condition") == "new":
                return price
        return prices[0] if prices else None

    @staticmethod
    def extract_buy_box_price(offers_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract the Buy Box price from a get_item_offers response."""
        body = offers_result.get("body") or offers_result
        payload = body.get("payload") or {}
        summary = payload.get("Summary") or {}
        prices = summary.get("BuyBoxPrices") or []
        return prices[0] if prices else None

    @staticmethod
    def extract_offer_count(offers_result: Dict[str, Any]) -> int:
        """Extract total offer count from a get_item_offers response."""
        body = offers_result.get("body") or offers_result
        payload = body.get("payload") or {}
        summary = payload.get("Summary") or {}
        return summary.get("TotalOfferCount", 0)

    @staticmethod
    def parse_competitive_result(
        result: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Parse getCompetitivePricing response into flat list per ASIN."""
        body = result.get("body") or result
        payload = body.get("payload") or []
        items = []
        for item in payload:
            asin = item.get("ASIN") or item.get("Identifiers", {}).get("MarketplaceASIN", {}).get("ASIN", "unknown")
            product = item.get("Product") or {}
            competitive = product.get("CompetitivePricing", {}).get("CompetitivePrices") or []
            sales_rankings = product.get("SalesRankings") or []
            offer_count = product.get("NumberOfOfferListings") or []

            prices = []
            for cp in competitive:
                price_info = cp.get("Price") or {}
                prices.append({
                    "listing_price": price_info.get("ListingPrice", {}).get("Amount"),
                    "shipping": price_info.get("Shipping", {}).get("Amount"),
                    "landed_price": price_info.get("LandedPrice", {}).get("Amount"),
                    "condition": cp.get("condition", "New"),
                    "fulfillment_channel": cp.get("fulfillmentChannel", ""),
                    "belongs_to_requester": cp.get("belongsToRequester", False),
                })

            items.append({
                "asin": asin,
                "competitive_prices": prices,
                "sales_rankings": [
                    {"category": sr.get("ProductCategoryId"), "rank": sr.get("Rank")}
                    for sr in sales_rankings
                ],
                "offer_counts": offer_count,
            })
        return items
