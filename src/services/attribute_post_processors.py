"""Config-driven post processors for rendered Amazon attributes."""

from __future__ import annotations

from typing import Any, Dict, Iterable


def apply_attribute_post_processors(
    names: Iterable[str],
    attrs: Dict[str, Any],
    marketplace_id: str,
) -> None:
    """Apply named post processors from product-type configuration."""
    processors = {
        "cabinet_attribute_shapes": _apply_cabinet_attribute_shapes,
    }
    for name in names or []:
        processor = processors.get(str(name))
        if processor is not None:
            processor(attrs, marketplace_id)


def _apply_cabinet_attribute_shapes(
    attrs: Dict[str, Any],
    marketplace_id: str,
) -> None:
    from src.services.amazon_listing_cabinet_attributes import (
        normalize_cabinet_attributes,
    )

    normalize_cabinet_attributes(attrs, marketplace_id)
