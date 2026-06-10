"""Amazon Listings Items API client."""
import logging
from typing import Any, Dict, List, Optional

from infrastructure.amazon.api_client import AmazonAPIClient
from infrastructure.amazon.config import AmazonConfig

logger = logging.getLogger(__name__)


class AmazonListingsClient:
    """Submits listing updates via the Listings Items API."""

    def __init__(
        self,
        api_client: Optional[AmazonAPIClient] = None,
        marketplace_id: Optional[str] = None,
        seller_id: Optional[str] = None,
    ):
        self.api_client = api_client or AmazonAPIClient()
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID
        self.seller_id = seller_id or AmazonConfig.SELLER_ID

    # ── existing SKU operations ──────────────────────────────────

    def patch_listings_item(
        self,
        sku: str,
        product_type: str,
        patches: List[Dict[str, Any]],
        issue_locale: str = "en_US",
    ) -> Dict[str, Any]:
        """Patch an existing listing item (price, quantity, etc.)."""
        path = f"/listings/2021-08-01/items/{self.seller_id}/{sku}"
        params = {
            "marketplaceIds": self.marketplace_id,
            "issueLocale": issue_locale,
        }
        body = {
            "productType": product_type,
            "patches": patches,
        }
        logger.info(
            "Patching listing SKU=%s productType=%s patches=%d",
            sku,
            product_type,
            len(patches),
        )
        return self.api_client.request("PATCH", path, params=params, json=body)

    def get_listings_item(
        self,
        sku: str,
        issue_locale: str = "en_US",
        included_data: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Retrieve an existing listing item by SKU."""
        path = f"/listings/2021-08-01/items/{self.seller_id}/{sku}"
        params = {
            "marketplaceIds": self.marketplace_id,
            "issueLocale": issue_locale,
        }
        if included_data:
            params["includedData"] = ",".join(included_data)
        return self.api_client.request("GET", path, params=params)

    def search_listings_items(
        self,
        issue_locale: str = "en_US",
        included_data: Optional[List[str]] = None,
        with_issue_severity: Optional[List[str]] = None,
        page_size: int = 20,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search listing items and optionally include issue details."""
        path = f"/listings/2021-08-01/items/{self.seller_id}"
        params: Dict[str, Any] = {
            "marketplaceIds": self.marketplace_id,
            "issueLocale": issue_locale,
            "pageSize": page_size,
        }
        if included_data:
            params["includedData"] = ",".join(included_data)
        if with_issue_severity:
            params["withIssueSeverity"] = ",".join(with_issue_severity)
        if page_token:
            params["pageToken"] = page_token
        return self.api_client.request("GET", path, params=params)

    # ── new listing creation ─────────────────────────────────────

    def put_listings_item(
        self,
        sku: str,
        product_type: str,
        attributes: Dict[str, Any],
        issue_locale: str = "en_US",
    ) -> Dict[str, Any]:
        """Create or fully replace a listing item.

        Returns the full API response with headers and body.
        """
        path = f"/listings/2021-08-01/items/{self.seller_id}/{sku}"
        params = {
            "marketplaceIds": self.marketplace_id,
            "issueLocale": issue_locale,
        }
        body = {
            "productType": product_type,
            "attributes": attributes,
        }
        logger.info(
            "Putting listing SKU=%s productType=%s attr_keys=%d",
            sku,
            product_type,
            len(attributes),
        )
        return self.api_client.request("PUT", path, params=params, json=body)

    def validation_preview(
        self,
        sku: str,
        product_type: str,
        attributes: Dict[str, Any],
        issue_locale: str = "en_US",
    ) -> Dict[str, Any]:
        """Validate a listing without creating it.

        Uses the VALIDATION_PREVIEW mode to check for issues before submission.
        """
        path = f"/listings/2021-08-01/items/{self.seller_id}/{sku}"
        params = {
            "marketplaceIds": self.marketplace_id,
            "issueLocale": issue_locale,
            "mode": "VALIDATION_PREVIEW",
        }
        body = {
            "productType": product_type,
            "attributes": attributes,
        }
        logger.info("Validation preview SKU=%s productType=%s", sku, product_type)
        return self.api_client.request("PUT", path, params=params, json=body)

    # ── delete ─────────────────────────────────────────────────────

    def delete_listings_item(
        self,
        sku: str,
        issue_locale: str = "en_US",
    ) -> Dict[str, Any]:
        """Delete a listing item by SKU."""
        path = f"/listings/2021-08-01/items/{self.seller_id}/{sku}"
        params = {
            "marketplaceIds": self.marketplace_id,
            "issueLocale": issue_locale,
        }
        logger.info("Deleting listing SKU=%s", sku)
        return self.api_client.request("DELETE", path, params=params)
