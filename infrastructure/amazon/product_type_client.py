"""Amazon Product Type Definitions API client."""
import logging
from typing import Any, Dict, List, Optional

import requests

from infrastructure.amazon.api_client import AmazonAPIClient
from infrastructure.amazon.config import AmazonConfig

logger = logging.getLogger(__name__)


class AmazonProductTypeClient:
    """Fetches product type schemas and requirements from SP-API."""

    def __init__(
        self,
        api_client: Optional[AmazonAPIClient] = None,
        marketplace_id: Optional[str] = None,
    ):
        self.api_client = api_client or AmazonAPIClient()
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID

    def search_product_types(self, keywords: str) -> List[str]:
        """Search for product type names matching keywords."""
        response = self.api_client.request(
            "GET",
            "/definitions/2020-09-01/productTypes",
            params={
                "marketplaceIds": self.marketplace_id,
                "keywords": keywords,
            },
        )
        return [t["name"] for t in response["body"].get("productTypes", [])]

    def get_schema_link(self, product_type: str) -> str:
        """Get the pre-signed S3 URL for a product type's JSON Schema."""
        response = self.api_client.request(
            "GET",
            f"/definitions/2020-09-01/productTypes/{product_type}",
            params={
                "marketplaceIds": self.marketplace_id,
                "requirementsEnum": "ENFORCED",
                "locale": "en_US",
            },
        )
        return response["body"]["schema"]["link"]["resource"]

    def get_schema(self, product_type: str) -> Dict[str, Any]:
        """Download and return the full JSON Schema for a product type."""
        s3_url = self.get_schema_link(product_type)
        logger.info("Downloading schema for %s", product_type)
        s3_resp = requests.get(s3_url, timeout=30)
        s3_resp.raise_for_status()
        return s3_resp.json()

    def get_requirements(self, product_type: str) -> Dict[str, Any]:
        """Get enforced requirements for a product type (without downloading schema)."""
        response = self.api_client.request(
            "GET",
            f"/definitions/2020-09-01/productTypes/{product_type}",
            params={
                "marketplaceIds": self.marketplace_id,
                "requirementsEnum": "ENFORCED",
                "locale": "en_US",
            },
        )
        return response["body"].get("requirementsEnforced", {})

    def get_required_properties(self, product_type: str) -> List[str]:
        """Download schema and return the list of required property names."""
        schema = self.get_schema(product_type)
        required = list(schema.get("required", []))
        for part in schema.get("allOf", []):
            required.extend(part.get("required", []))
        return sorted(set(required))
