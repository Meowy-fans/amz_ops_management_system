"""Standardized product model — vendor-agnostic representation of a product
ready for Amazon listing generation."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DimensionSpec:
    """Physical dimensions in inches and pounds (Amazon standard)."""

    length: Optional[float] = None  # inches
    width: Optional[float] = None  # inches
    height: Optional[float] = None  # inches
    weight: Optional[float] = None  # pounds
    assembled_length: Optional[float] = None
    assembled_width: Optional[float] = None
    assembled_height: Optional[float] = None
    assembled_weight: Optional[float] = None
    source_unit: str = "in"  # original unit from supplier


@dataclass
class PriceSpec:
    """Price information from supplier."""

    cost: Optional[float] = None  # purchase cost in USD
    shipping_fee: Optional[float] = None
    currency: str = "USD"


@dataclass
class InventorySpec:
    """Inventory quantity from supplier."""

    quantity: int = 0
    next_arrival_date: Optional[str] = None
    next_arrival_qty: Optional[int] = None


@dataclass
class StandardProduct:
    """Vendor-agnostic product representation.

    All supplier-specific field extraction logic lives in the normalizer;
    downstream code (LLM, mapper, submitter) works with this model only.
    """

    # Identity
    sku: str  # meow_sku (internal Amazon-facing SKU)
    vendor_sku: str  # supplier's own SKU
    vendor_source: str  # "giga", etc.

    # Core content
    name: str = ""  # product title / name from supplier
    description: str = ""  # raw description (may contain HTML)
    bullet_points: List[str] = field(default_factory=list)  # up to 5
    images: List[str] = field(default_factory=list)  # main_image first, then alternates
    videos: List[str] = field(default_factory=list)
    documents: List[str] = field(default_factory=list)  # PDFs, manuals

    # Classification
    category_hint: str = ""  # supplier's own category label
    attributes: Dict[str, str] = field(default_factory=dict)  # normalized key→value pairs

    # Physical
    dimensions: Optional[DimensionSpec] = None
    dimensions_package: Optional[DimensionSpec] = None  # package/box dimensions

    # Commercial
    price: Optional[PriceSpec] = None
    inventory: Optional[InventorySpec] = None

    # Variations
    variant_associations: List[str] = field(default_factory=list)  # related vendor SKUs
    is_variation_parent: bool = False

    # Flags
    is_oversize: bool = False
    contains_battery: bool = False
    contains_hazmat: bool = False
    requires_assembly: Optional[bool] = None
    has_gtin_exemption: bool = False

    # Source metadata (for debugging / audit)
    raw_source_data: Dict[str, Any] = field(default_factory=dict)
