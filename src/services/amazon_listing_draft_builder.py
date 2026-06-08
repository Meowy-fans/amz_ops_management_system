"""Build API-native Amazon listing drafts from persisted product data."""

from typing import Any, Dict, List

from src.models.amazon_listing import (
    AmazonListingDraft,
    ListingContent,
    ListingOffer,
)
from src.services.product_normalizer import GigaProductNormalizer


class AmazonListingDraftBuilder:
    """Converts DB product rows into AmazonListingDraft objects."""

    def __init__(self, normalizer: GigaProductNormalizer | None = None):
        self.normalizer = normalizer or GigaProductNormalizer()

    def build(
        self,
        product_data: Dict[str, Any],
        product_type: str,
    ) -> AmazonListingDraft:
        if not product_data:
            raise ValueError("product_data is required")

        sku = str(product_data.get("meow_sku") or "").strip()
        vendor_sku = str(product_data.get("vendor_sku") or "").strip()
        if not sku:
            raise ValueError("meow_sku is required to build listing draft")
        if not vendor_sku:
            raise ValueError("vendor_sku is required to build listing draft")

        raw_data = product_data.get("raw_data") or {}
        standard_product = self.normalizer.normalize(
            raw_data=raw_data,
            vendor_sku=vendor_sku,
            meow_sku=sku,
            inventory_qty=int(product_data.get("total_quantity") or 0),
        )

        content = ListingContent(
            title=self._first_text(
                product_data.get("product_name"),
                standard_product.name,
            ),
            bullets=self._bullets(product_data, standard_product.bullet_points),
            description=self._first_text(
                product_data.get("product_description"),
                standard_product.description,
            ),
        )

        offer = ListingOffer(
            price=self._to_float(product_data.get("final_price")),
            quantity=int(product_data.get("total_quantity") or 0),
        )

        return AmazonListingDraft(
            sku=sku,
            vendor_sku=vendor_sku,
            product_type=product_type.upper(),
            standard_product=standard_product,
            content=content,
            offer=offer,
            source_trace={
                "vendor_source": standard_product.vendor_source,
                "vendor_sku": vendor_sku,
                "category_name": product_data.get("category_name"),
            },
        )

    @staticmethod
    def _first_text(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @classmethod
    def _bullets(
        cls,
        product_data: Dict[str, Any],
        fallback: List[str],
    ) -> List[str]:
        generated = [
            cls._first_text(product_data.get(f"selling_point_{idx}"))
            for idx in range(1, 6)
        ]
        bullets = [item for item in generated if item]
        if bullets:
            return bullets[:5]
        return [str(item).strip() for item in fallback if str(item).strip()][:5]

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
