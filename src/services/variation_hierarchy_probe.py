"""Read-only probe for Amazon variation hierarchy facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VariationHierarchyProbeResult:
    """Observed online variation facts for one parent SKU."""

    parent_sku: str
    parent_asin: Optional[str] = None
    child_asins: List[str] = field(default_factory=list)
    relationship_snapshot: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "parent_sku": self.parent_sku,
            "parent_asin": self.parent_asin,
            "child_asins": self.child_asins,
            "relationship_snapshot": self.relationship_snapshot,
            "warnings": self.warnings,
        }


class VariationHierarchyProbe:
    """Fetches parent ASIN and catalog relationships without mutating Amazon."""

    def __init__(self, listings_client: Any, catalog_client: Any):
        self.listings_client = listings_client
        self.catalog_client = catalog_client

    def probe_parent(self, parent_sku: str) -> VariationHierarchyProbeResult:
        result = VariationHierarchyProbeResult(parent_sku=str(parent_sku))
        listing = self.listings_client.get_listings_item(
            parent_sku,
            included_data=["summaries", "attributes", "productTypes"],
        )
        listing_body = listing.get("body") if isinstance(listing, dict) else listing
        result.parent_asin = self._extract_asin(listing_body or {})
        if not result.parent_asin:
            result.warnings.append("parent_asin_not_found")
            return result

        catalog = self.catalog_client.get_catalog_item(
            result.parent_asin,
            included_data=["relationships"],
        )
        catalog_body = catalog.get("body") if isinstance(catalog, dict) else catalog
        relationships = (catalog_body or {}).get("relationships") or []
        result.relationship_snapshot = {"relationships": relationships}
        result.child_asins = self._extract_child_asins(relationships)
        if not result.child_asins:
            result.warnings.append("child_asins_not_found")
        return result

    @staticmethod
    def _extract_asin(listing_body: Dict[str, Any]) -> Optional[str]:
        summaries = listing_body.get("summaries") or []
        if summaries and isinstance(summaries[0], dict) and summaries[0].get("asin"):
            return str(summaries[0]["asin"])
        if listing_body.get("asin"):
            return str(listing_body["asin"])
        return None

    @classmethod
    def _extract_child_asins(cls, relationships: Any) -> List[str]:
        found: List[str] = []
        cls._collect_asins(relationships, found)
        return found

    @classmethod
    def _collect_asins(cls, node: Any, found: List[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_lower = str(key).lower()
                if key_lower in {"childasin", "child_asin", "asin"}:
                    cls._append_asin(value, found)
                elif key_lower in {
                    "childasins",
                    "child_asins",
                    "children",
                    "variationchildren",
                    "variation_children",
                }:
                    cls._collect_asins(value, found)
                else:
                    cls._collect_asins(value, found)
        elif isinstance(node, list):
            for item in node:
                cls._collect_asins(item, found)
        elif isinstance(node, str):
            cls._append_asin(node, found)

    @staticmethod
    def _append_asin(value: Any, found: List[str]) -> None:
        text = str(value or "").strip()
        if len(text) == 10 and text.upper().startswith("B") and text not in found:
            found.append(text)
