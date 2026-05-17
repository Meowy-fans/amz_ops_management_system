"""Product normalizers — convert supplier-specific raw data into StandardProduct.

Each supplier gets a normalizer class registered in NORMALIZER_REGISTRY.
The normalizer is the ONLY place where supplier-specific field names appear.
"""

import logging
from typing import Any, Dict, List, Optional

from src.models.product import (
    DimensionSpec,
    InventorySpec,
    PriceSpec,
    StandardProduct,
)

logger = logging.getLogger(__name__)


# ── registry ───────────────────────────────────────────────────────

NORMALIZER_REGISTRY: Dict[str, type] = {}


def get_normalizer(vendor_source: str) -> "GigaProductNormalizer":
    cls = NORMALIZER_REGISTRY.get(vendor_source)
    if cls is None:
        raise ValueError(f"No normalizer registered for vendor_source={vendor_source}")
    return cls()


# ── Giga normalizer ────────────────────────────────────────────────

class GigaProductNormalizer:
    """Converts Giga raw_data JSONB into a StandardProduct."""

    # unit conversion: source unit → inches
    _INCH_FACTORS = {"in": 1.0, "cm": 1 / 2.54, "mm": 1 / 25.4, "m": 39.3701}
    # unit conversion: source unit → pounds
    _LB_FACTORS = {"lb": 1.0, "kg": 2.20462, "g": 0.00220462}

    def normalize(
        self,
        raw_data: Dict[str, Any],
        vendor_sku: str,
        meow_sku: str = "",
        price_data: Optional[Dict[str, Any]] = None,
        inventory_qty: int = 0,
        is_oversize: bool = False,
    ) -> StandardProduct:
        """Convert Giga raw_data to StandardProduct.

        Args:
            raw_data: The raw_data JSONB column from giga_product_sync_records.
            vendor_sku: The Giga SKU (vendor_sku column).
            meow_sku: The internal Amazon SKU.
            price_data: Optional row from giga_product_base_prices.
            inventory_qty: Quantity from giga_inventory.
            is_oversize: From giga_product_sync_records.is_oversize.
        """
        dim_unit = (raw_data.get("lengthUnit") or "in").lower()
        wt_unit = (raw_data.get("weightUnit") or "lb").lower()
        dim_factor = self._INCH_FACTORS.get(dim_unit, 1.0)
        wt_factor = self._LB_FACTORS.get(wt_unit, 1.0)

        # ── dimensions ─────────────────────────────────────────────
        dims = DimensionSpec(
            length=self._to_float(raw_data.get("length")) * dim_factor
            if raw_data.get("length")
            else None,
            width=self._to_float(raw_data.get("width")) * dim_factor
            if raw_data.get("width")
            else None,
            height=self._to_float(raw_data.get("height")) * dim_factor
            if raw_data.get("height")
            else None,
            weight=self._to_float(raw_data.get("weight")) * wt_factor
            if raw_data.get("weight")
            else None,
            assembled_length=self._to_float(raw_data.get("assembledLength")),
            assembled_width=self._to_float(raw_data.get("assembledWidth")),
            assembled_height=self._to_float(raw_data.get("assembledHeight")),
            assembled_weight=self._to_float(raw_data.get("assembledWeight")),
            source_unit=dim_unit,
        )

        # ── package dimensions (from comboInfo[0] if present) ───────
        pkg_dims: Optional[DimensionSpec] = None
        combo = raw_data.get("comboInfo") or []
        if isinstance(combo, list) and combo:
            c0 = combo[0]
            pkg_dims = DimensionSpec(
                length=self._to_float(c0.get("length")) * dim_factor
                if c0.get("length")
                else None,
                width=self._to_float(c0.get("width")) * dim_factor
                if c0.get("width")
                else None,
                height=self._to_float(c0.get("height")) * dim_factor
                if c0.get("height")
                else None,
                assembled_length=self._to_float(raw_data.get("assembledLength")),
                assembled_width=self._to_float(raw_data.get("assembledWidth")),
                assembled_height=self._to_float(raw_data.get("assembledHeight")),
                source_unit=dim_unit,
            )

        # ── images (main first, then alternates) ────────────────────
        images: List[str] = []
        main_img = raw_data.get("mainImageUrl", "")
        if main_img:
            images.append(main_img)
        for url in raw_data.get("imageUrls") or []:
            if url and url != main_img:
                images.append(url)

        # ── attributes (flattened) ──────────────────────────────────
        attrs: Dict[str, str] = {}
        for k, v in (raw_data.get("attributes") or {}).items():
            attrs[str(k)] = str(v)
        # add top-level fields as attributes for mapping
        if raw_data.get("mpn"):
            attrs["mpn"] = str(raw_data["mpn"])
        if raw_data.get("placeOfOrigin"):
            attrs["place_of_origin"] = str(raw_data["placeOfOrigin"])
        seller = raw_data.get("sellerInfo") or {}
        if seller.get("sellerStore"):
            attrs["seller_name"] = str(seller["sellerStore"])
        if seller.get("sellerCode"):
            attrs["seller_code"] = str(seller["sellerCode"])
        if raw_data.get("material"):
            attrs["material"] = str(raw_data["material"])
        if raw_data.get("color"):
            attrs["color"] = str(raw_data["color"])
        if raw_data.get("style"):
            attrs["style"] = str(raw_data["style"])

        # ── bullet points ──────────────────────────────────────────
        characteristics = raw_data.get("characteristics") or []
        bullet_points = [str(c) for c in characteristics[:5]] if isinstance(characteristics, list) else []

        # ── price ───────────────────────────────────────────────────
        price: Optional[PriceSpec] = None
        if price_data:
            price = PriceSpec(
                cost=self._to_float(price_data.get("base_price")),
                shipping_fee=self._to_float(price_data.get("shipping_fee")),
                currency=price_data.get("currency", "USD"),
            )

        # ── inventory ──────────────────────────────────────────────
        inventory = InventorySpec(quantity=int(inventory_qty or 0))

        # ── variations ─────────────────────────────────────────────
        variant_associations: List[str] = []
        assoc = raw_data.get("associateProductList") or []
        if isinstance(assoc, list):
            variant_associations = [str(a) for a in assoc]

        # ── flags ───────────────────────────────────────────────────
        batt = str(raw_data.get("lithiumBatteryContained", "No")).lower()
        customized = str(raw_data.get("customized", "No")).lower()

        return StandardProduct(
            sku=meow_sku,
            vendor_sku=vendor_sku,
            vendor_source="giga",
            name=str(raw_data.get("name") or ""),
            description=str(raw_data.get("description") or ""),
            bullet_points=bullet_points,
            images=images,
            videos=[str(v) for v in (raw_data.get("videoUrls") or [])],
            documents=[str(d) for d in (raw_data.get("fileUrls") or [])],
            category_hint=str(raw_data.get("category") or ""),
            attributes=attrs,
            dimensions=dims,
            dimensions_package=pkg_dims,
            price=price,
            inventory=inventory,
            variant_associations=variant_associations,
            is_oversize=is_oversize,
            contains_battery=batt not in ("no", ""),
            requires_assembly=(customized == "yes" or raw_data.get("assemblyRequired") == "Yes"),
            raw_source_data=raw_data,
        )

    @staticmethod
    def _to_float(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None


NORMALIZER_REGISTRY["giga"] = GigaProductNormalizer
