"""Amazon Catalog Items API client (v2022-04-01).

Provides product details, BSR, attributes, and keyword search.
"""

import logging
from typing import Any, Dict, List, Optional

from infrastructure.amazon.api_client import AmazonAPIClient
from infrastructure.amazon.config import AmazonConfig

logger = logging.getLogger(__name__)


class AmazonCatalogClient:
    """Queries Catalog Items API for product metadata and BSR.

    Endpoints:
      - getCatalogItem: single ASIN details with selectable includedData
      - searchCatalogItems: keyword-based ASIN search
    """

    _CATALOG_PATH = "/catalog/2022-04-01/items"

    def __init__(
        self,
        api_client: Optional[AmazonAPIClient] = None,
        marketplace_id: Optional[str] = None,
    ):
        self.api_client = api_client or AmazonAPIClient()
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID

    def get_catalog_item(
        self,
        asin: str,
        included_data: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get detailed info for a single ASIN.

        includedData options (comma-separated):
          summaries, salesRanks, attributes, identifiers, images,
          relationships, dimensions, productTypes, vendorDetails

        Rate: 5 req/s, burst 40.
        """
        path = f"{self._CATALOG_PATH}/{asin}"
        params: Dict[str, Any] = {
            "marketplaceIds": self.marketplace_id,
        }
        if included_data:
            params["includedData"] = ",".join(included_data)

        logger.info("getCatalogItem: %s includedData=%s", asin, params.get("includedData"))
        return self.api_client.request("GET", path, params=params)

    def search_catalog_items(
        self,
        keywords: Optional[List[str]] = None,
        identifiers: Optional[List[str]] = None,
        identifiers_type: str = "ASIN",
        included_data: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search catalog items by keywords or identifiers.

        keywords: List of search terms (Amazon ranks results by relevance).
        identifiers: List of ASINs/UPCs/EANs to look up.
        identifiers_type: "ASIN", "UPC", "EAN", "ISBN", etc.

        Rate: 5 req/s, burst 40.
        """
        path = self._CATALOG_PATH
        params: Dict[str, Any] = {
            "marketplaceIds": self.marketplace_id,
        }
        if keywords:
            params["keywords"] = keywords
        if identifiers:
            params["identifiers"] = ",".join(identifiers)
            params["identifiersType"] = identifiers_type
        if included_data:
            params["includedData"] = ",".join(included_data)

        logger.info(
            "searchCatalogItems: keywords=%s identifiers=%s",
            keywords[:3] if keywords else None,
            identifiers[:5] if identifiers else None,
        )
        return self.api_client.request("GET", path, params=params)

    # ── convenience methods ─────────────────────────────────────────

    def get_bsr(self, asin: str) -> Optional[List[Dict[str, Any]]]:
        """Get Best Sellers Rank for a single ASIN."""
        result = self.get_catalog_item(asin, included_data=["salesRanks"])
        body = result.get("body") or result
        sales_ranks = body.get("salesRanks") or []
        return [
            {
                "category_id": sr.get("classificationRanks", [{}])[0].get("title", ""),
                "rank": sr.get("classificationRanks", [{}])[0].get("rank"),
                "link": sr.get("classificationRanks", [{}])[0].get("link", ""),
            }
            for sr in sales_ranks
        ]

    def get_summary(self, asin: str) -> Dict[str, str]:
        """Get basic product summary (title, brand, category)."""
        result = self.get_catalog_item(asin, included_data=["summaries", "productTypes"])
        body = result.get("body") or result
        summaries = body.get("summaries") or []
        product_types = body.get("productTypes") or []
        if summaries:
            s = summaries[0]
            pt = product_types[0].get("productType", "") if product_types else ""
            return {
                "asin": s.get("asin", asin),
                "title": s.get("itemName", ""),
                "brand": s.get("brand", ""),
                "manufacturer": s.get("manufacturer", ""),
                "product_type": pt or s.get("productType", ""),
                "item_classification": s.get("itemClassification", ""),
            }
        return {"asin": asin, "title": "", "brand": "", "product_type": ""}

    def batch_get_summaries(
        self,
        asins: List[str],
        max_per_request: int = 20,
    ) -> Dict[str, Dict[str, str]]:
        """Get summaries for multiple ASINs using searchCatalogItems."""
        results: Dict[str, Dict[str, str]] = {}
        for i in range(0, len(asins), max_per_request):
            batch = asins[i : i + max_per_request]
            try:
                resp = self.search_catalog_items(
                    identifiers=batch,
                    identifiers_type="ASIN",
                    included_data=["summaries", "salesRanks", "productTypes"],
                )
                body = resp.get("body") or resp
                items = body.get("items") or []
                for item in items:
                    asin = item.get("asin", "")
                    summaries = item.get("summaries") or []
                    sales_ranks = item.get("salesRanks") or []
                    product_types = item.get("productTypes") or []
                    s = summaries[0] if summaries else {}
                    pt = (
                        product_types[0].get("productType", "")
                        if product_types
                        else ""
                    )
                    bsr = None
                    if sales_ranks:
                        ranks = sales_ranks[0].get("classificationRanks") or []
                        bsr = ranks[0].get("rank") if ranks else None
                    results[asin] = {
                        "asin": asin,
                        "title": s.get("itemName", ""),
                        "brand": s.get("brand", ""),
                        "product_type": pt or s.get("productType", ""),
                        "bsr": bsr,
                    }
            except Exception as exc:
                logger.error("batch_get_summaries failed for batch: %s", exc)
        return results
