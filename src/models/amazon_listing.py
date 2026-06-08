"""API-native Amazon listing draft models."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.models.product import StandardProduct


@dataclass
class ListingContent:
    """Amazon-facing listing content."""

    title: str = ""
    bullets: List[str] = field(default_factory=list)
    description: str = ""
    search_terms: str = ""
    generic_keyword: str = ""


@dataclass
class ListingOffer:
    """Commercial offer data for a listing."""

    price: Optional[float] = None
    quantity: int = 0
    currency: str = "USD"
    condition_type: str = "new_new"


@dataclass
class ListingVariation:
    """Variation relationship data for a listing."""

    parentage_level: Optional[str] = None
    parent_sku: Optional[str] = None
    variation_theme: Optional[str] = None
    child_relationship_type: Optional[str] = None
    theme_attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AmazonListingDraft:
    """System-owned draft that can be rendered to SP-API attributes."""

    sku: str
    vendor_sku: str
    product_type: str
    standard_product: StandardProduct
    content: ListingContent
    offer: ListingOffer = field(default_factory=ListingOffer)
    variation: ListingVariation = field(default_factory=ListingVariation)
    marketplace_id: str = "ATVPDKIKX0DER"
    operation: str = "create"
    source_trace: Dict[str, Any] = field(default_factory=dict)
