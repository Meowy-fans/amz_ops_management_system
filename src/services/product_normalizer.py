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

        combo = raw_data.get("comboInfo") or []
        combo_dims = self._combo_dimensions(combo, dim_factor, wt_factor, dim_unit)

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
        if self._is_empty_dimensions(dims) and combo_dims is not None:
            dims = combo_dims
        elif self._has_no_spatial_dimensions(dims) and combo_dims is not None:
            dims.length = combo_dims.length
            dims.width = combo_dims.width
            dims.height = combo_dims.height
            dims.assembled_length = combo_dims.assembled_length
            dims.assembled_width = combo_dims.assembled_width
            dims.assembled_height = combo_dims.assembled_height
            if dims.weight is None:
                dims.weight = combo_dims.weight
            if dims.assembled_weight is None:
                dims.assembled_weight = combo_dims.assembled_weight

        # ── package dimensions (from comboInfo[0] if present) ───────
        pkg_dims: Optional[DimensionSpec] = None
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

    @classmethod
    def _combo_dimensions(
        cls,
        combo: Any,
        dim_factor: float,
        wt_factor: float,
        dim_unit: str,
    ) -> Optional[DimensionSpec]:
        if not isinstance(combo, list) or not combo:
            return None
        lengths: List[float] = []
        widths: List[float] = []
        heights: List[float] = []
        total_weight = 0.0
        has_weight = False
        for item in combo:
            if not isinstance(item, dict):
                continue
            qty = cls._to_float(item.get("qty")) or 1
            length = cls._to_float(item.get("length"))
            width = cls._to_float(item.get("width"))
            height = cls._to_float(item.get("height"))
            weight = cls._to_float(item.get("weight"))
            if length is not None:
                lengths.append(length * dim_factor)
            if width is not None:
                widths.append(width * dim_factor)
            if height is not None:
                heights.append(height * dim_factor)
            if weight is not None:
                total_weight += weight * wt_factor * qty
                has_weight = True
        if not lengths and not widths and not heights and not has_weight:
            return None
        return DimensionSpec(
            length=max(lengths) if lengths else None,
            width=max(widths) if widths else None,
            height=max(heights) if heights else None,
            weight=round(total_weight, 2) if has_weight else None,
            assembled_length=max(lengths) if lengths else None,
            assembled_width=max(widths) if widths else None,
            assembled_height=max(heights) if heights else None,
            assembled_weight=round(total_weight, 2) if has_weight else None,
            source_unit=dim_unit,
        )

    @staticmethod
    def _is_empty_dimensions(dims: DimensionSpec) -> bool:
        return all(
            value is None
            for value in (
                dims.length,
                dims.width,
                dims.height,
                dims.weight,
                dims.assembled_length,
                dims.assembled_width,
                dims.assembled_height,
                dims.assembled_weight,
            )
        )

    @staticmethod
    def _has_no_spatial_dimensions(dims: DimensionSpec) -> bool:
        return all(
            value is None
            for value in (
                dims.length,
                dims.width,
                dims.height,
                dims.assembled_length,
                dims.assembled_width,
                dims.assembled_height,
            )
        )


NORMALIZER_REGISTRY["giga"] = GigaProductNormalizer
