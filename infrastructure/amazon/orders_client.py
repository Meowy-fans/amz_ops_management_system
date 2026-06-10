"""Amazon Orders API v0 client (read-only)."""
import logging
from typing import Any, Dict, List, Optional

from infrastructure.amazon.api_client import AmazonAPIClient
from infrastructure.amazon.config import AmazonConfig

logger = logging.getLogger(__name__)


class AmazonOrdersClient:
    """Fetches seller orders through the Orders API."""

    def __init__(
        self,
        api_client: Optional[AmazonAPIClient] = None,
        marketplace_id: Optional[str] = None,
    ):
        self.api_client = api_client or AmazonAPIClient()
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID

    def get_orders(
        self,
        created_after: str,
        order_statuses: Optional[List[str]] = None,
        fulfillment_channels: Optional[List[str]] = None,
        max_results: int = 100,
        next_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List orders created after a timestamp."""
        params: Dict[str, Any] = {
            "MarketplaceIds": self.marketplace_id,
            "CreatedAfter": created_after,
            "MaxResultsPerPage": max_results,
        }
        if order_statuses:
            params["OrderStatuses"] = order_statuses
        if fulfillment_channels:
            params["FulfillmentChannels"] = fulfillment_channels
        if next_token:
            params["NextToken"] = next_token
        logger.info(
            "Fetching Amazon orders created_after=%s statuses=%s channels=%s",
            created_after,
            order_statuses,
            fulfillment_channels,
        )
        return self.api_client.request("GET", "/orders/v0/orders", params=params)

    def get_order(self, amazon_order_id: str) -> Dict[str, Any]:
        """Fetch a single order by Amazon order ID."""
        path = f"/orders/v0/orders/{amazon_order_id}"
        return self.api_client.request("GET", path)

    def get_order_items(self, amazon_order_id: str) -> Dict[str, Any]:
        """Fetch line items for an order."""
        path = f"/orders/v0/orders/{amazon_order_id}/orderItems"
        return self.api_client.request("GET", path)

    def get_order_address(self, amazon_order_id: str) -> Dict[str, Any]:
        """Fetch the shipping address for an order (may be partially redacted)."""
        path = f"/orders/v0/orders/{amazon_order_id}/address"
        return self.api_client.request("GET", path)
