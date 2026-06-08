"""Repository for Amazon Listings Items API cache."""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class AmazonListingItemCacheRepository:
    """Persists listing facts returned by Listings Items API."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_items(self, items: List[Dict[str, Any]]) -> int:
        if not items:
            return 0
        rows = [self._row_from_item(item) for item in items if item.get("sku")]
        if not rows:
            return 0

        query = text("""
            INSERT INTO amazon_listing_items_cache (
                sku, asin, product_type, listing_status, summaries, attributes,
                issues, offers, fulfillment_availability, relationships, raw_item,
                amazon_last_updated_at, last_seen_at, updated_at
            ) VALUES (
                :sku, :asin, :product_type, :listing_status, :summaries, :attributes,
                :issues, :offers, :fulfillment_availability, :relationships, :raw_item,
                :amazon_last_updated_at, NOW(), NOW()
            )
            ON CONFLICT (sku) DO UPDATE SET
                asin = EXCLUDED.asin,
                product_type = EXCLUDED.product_type,
                listing_status = EXCLUDED.listing_status,
                summaries = EXCLUDED.summaries,
                attributes = EXCLUDED.attributes,
                issues = EXCLUDED.issues,
                offers = EXCLUDED.offers,
                fulfillment_availability = EXCLUDED.fulfillment_availability,
                relationships = EXCLUDED.relationships,
                raw_item = EXCLUDED.raw_item,
                amazon_last_updated_at = EXCLUDED.amazon_last_updated_at,
                last_seen_at = NOW(),
                updated_at = NOW();
        """)
        self.db.execute(query, rows)
        self.db.commit()
        return len(rows)

    @staticmethod
    def _row_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
        summaries = item.get("summaries") or []
        first_summary = summaries[0] if summaries else {}
        product_types = item.get("productTypes") or []
        first_product_type = product_types[0] if product_types else {}
        product_type = (
            first_summary.get("productType")
            or first_product_type.get("productType")
            or item.get("productType")
        )
        return {
            "sku": item.get("sku"),
            "asin": first_summary.get("asin") or item.get("asin"),
            "product_type": product_type,
            "listing_status": json.dumps(first_summary.get("status") or []),
            "summaries": json.dumps(summaries, default=str),
            "attributes": json.dumps(item.get("attributes") or {}, default=str),
            "issues": json.dumps(item.get("issues") or [], default=str),
            "offers": json.dumps(item.get("offers") or [], default=str),
            "fulfillment_availability": json.dumps(
                item.get("fulfillmentAvailability") or [], default=str
            ),
            "relationships": json.dumps(item.get("relationships") or [], default=str),
            "raw_item": json.dumps(item, default=str),
            "amazon_last_updated_at": first_summary.get("lastUpdatedDate"),
        }
