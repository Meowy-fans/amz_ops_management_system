"""Read-only probe for Amazon variation hierarchy facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VariationHierarchyProbeResult:
    """Observed online variation facts for one parent SKU."""

    parent_sku: str
    probe_status: str = "not_started"
    parent_asin: Optional[str] = None
    child_asins: List[str] = field(default_factory=list)
    parent_listing_snapshot: Dict[str, Any] = field(default_factory=dict)
    catalog_relationship_snapshot: Dict[str, Any] = field(default_factory=dict)
    online_sibling_facts: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "parent_sku": self.parent_sku,
            "probe_status": self.probe_status,
            "parent_asin": self.parent_asin,
            "child_asins": self.child_asins,
            "parent_listing_snapshot": self.parent_listing_snapshot,
            "catalog_relationship_snapshot": self.catalog_relationship_snapshot,
            "online_sibling_facts": self.online_sibling_facts,
            "warnings": self.warnings,
        }


class VariationHierarchyProbe:
    """Fetches parent ASIN and catalog relationships without mutating Amazon."""

    DEFAULT_MAX_DEPTH = 8

    def __init__(
        self,
        listings_client: Any,
        catalog_client: Any,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ):
        self.listings_client = listings_client
        self.catalog_client = catalog_client
        self.max_depth = max(1, int(max_depth))

    def probe_parent(self, parent_sku: str) -> VariationHierarchyProbeResult:
        result = VariationHierarchyProbeResult(parent_sku=str(parent_sku))
        try:
            listing = self.listings_client.get_listings_item(
                parent_sku,
                included_data=["summaries", "attributes", "productTypes"],
            )
        except Exception as exc:
            result.probe_status = "parent_lookup_failed"
            result.warnings.append(f"parent_lookup_failed: {exc}")
            return result
        listing_body = listing.get("body") if isinstance(listing, dict) else listing
        result.parent_listing_snapshot = listing_body or {}
        result.parent_asin = self._extract_asin(listing_body or {})
        if not result.parent_asin:
            result.probe_status = "parent_asin_not_found"
            result.warnings.append("parent_asin_not_found")
            return result

        try:
            catalog = self.catalog_client.get_catalog_item(
                result.parent_asin,
                included_data=["relationships"],
            )
        except Exception as exc:
            result.probe_status = "catalog_relationships_failed"
            result.warnings.append(f"catalog_relationships_failed: {exc}")
            return result
        catalog_body = catalog.get("body") if isinstance(catalog, dict) else catalog
        relationships = (catalog_body or {}).get("relationships") or []
        result.catalog_relationship_snapshot = {"relationships": relationships}
        result.child_asins = self._extract_child_asins(relationships)
        result.online_sibling_facts = self._extract_sibling_facts(relationships)
        if not result.child_asins:
            result.probe_status = "child_asins_not_found"
            result.warnings.append("child_asins_not_found")
            return result
        usable_facts = [
            item for item in result.online_sibling_facts
            if item.get("variation_attributes")
        ]
        if not usable_facts:
            result.probe_status = "insufficient_online_facts"
            result.warnings.append("insufficient_online_facts")
            return result
        result.probe_status = "facts_collected"
        return result

    @staticmethod
    def _extract_asin(listing_body: Dict[str, Any]) -> Optional[str]:
        summaries = listing_body.get("summaries") or []
        if summaries and isinstance(summaries[0], dict) and summaries[0].get("asin"):
            return str(summaries[0]["asin"])
        if listing_body.get("asin"):
            return str(listing_body["asin"])
        return None

    def _extract_child_asins(self, relationships: Any) -> List[str]:
        found: List[str] = []
        self._collect_asins(relationships, found, max_depth=self.max_depth)
        return found

    @classmethod
    def _collect_asins(
        cls,
        node: Any,
        found: List[str],
        max_depth: int,
        depth: int = 0,
    ) -> None:
        if depth > max_depth:
            return
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
                    cls._collect_asins(value, found, max_depth, depth + 1)
                else:
                    cls._collect_asins(value, found, max_depth, depth + 1)
        elif isinstance(node, list):
            for item in node:
                cls._collect_asins(item, found, max_depth, depth + 1)
        elif isinstance(node, str):
            cls._append_asin(node, found)

    @staticmethod
    def _append_asin(value: Any, found: List[str]) -> None:
        text = str(value or "").strip()
        if len(text) == 10 and text.upper().startswith("B") and text not in found:
            found.append(text)

    def _extract_sibling_facts(self, relationships: Any) -> List[Dict[str, Any]]:
        facts: List[Dict[str, Any]] = []
        self._collect_sibling_facts(relationships, facts, depth=0)
        return facts

    def _collect_sibling_facts(
        self,
        node: Any,
        facts: List[Dict[str, Any]],
        depth: int,
    ) -> None:
        if depth > self.max_depth:
            return
        if isinstance(node, dict):
            fact = self._fact_from_node(node)
            if fact:
                facts.append(fact)
            for value in node.values():
                self._collect_sibling_facts(value, facts, depth + 1)
        elif isinstance(node, list):
            for item in node:
                self._collect_sibling_facts(item, facts, depth + 1)

    def _fact_from_node(self, node: Dict[str, Any]) -> Dict[str, Any] | None:
        asin = self._node_asin(node)
        attrs = self._node_variation_attributes(node)
        if not asin and not attrs:
            return None
        return {
            "asin": asin,
            "sku": self._node_text(node, ("sku", "sellerSku", "seller_sku")),
            "variation_attributes": attrs,
            "raw": node,
        }

    @classmethod
    def _node_asin(cls, node: Dict[str, Any]) -> Optional[str]:
        for key in ("asin", "childAsin", "child_asin"):
            value = node.get(key)
            text = str(value or "").strip()
            if len(text) == 10 and text.upper().startswith("B"):
                return text
        return None

    @staticmethod
    def _node_text(node: Dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
        for key in keys:
            value = node.get(key)
            if value:
                return str(value)
        return None

    @classmethod
    def _node_variation_attributes(cls, node: Dict[str, Any]) -> Dict[str, Any]:
        for key in (
            "variation_attributes",
            "variationAttributes",
            "variationThemeAttributes",
            "attributes",
        ):
            value = node.get(key)
            if isinstance(value, dict):
                return dict(value)
            if isinstance(value, list):
                parsed = cls._attrs_from_list(value)
                if parsed:
                    return parsed
        return {}

    @staticmethod
    def _attrs_from_list(items: List[Any]) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("name")
                or item.get("attributeName")
                or item.get("attribute_name")
            )
            value = item.get("value") or item.get("attributeValue")
            if name and value not in (None, ""):
                attrs[str(name)] = value
        return attrs
