"""CABINET-specific SP-API attribute normalization."""
from typing import Any, Dict


_DOOR_STYLES = {
    "arched": "Arched",
    "flat panel": "Flat Panel",
    "glass front": "Glass Front",
    "louvered": "Louvered",
    "open frame": "Open Frame",
    "raised panel": "Raised Panel",
    "recessed panel": "Recessed Panel",
    "shaker": "Shaker",
    "shutter": "Shutter",
    "slab": "Slab",
}


def normalize_cabinet_attributes(
    attrs: Dict[str, Any],
    marketplace_id: str,
) -> None:
    """Normalize CABINET-only attributes to Product Type schema shapes."""
    attrs.pop("item_type_name", None)
    attrs.pop("target_audience_base", None)
    _normalize_door(attrs, marketplace_id)


def _normalize_door(attrs: Dict[str, Any], marketplace_id: str) -> None:
    style = _cabinet_door_style(_extract_door_style(attrs.get("door")))
    attrs["door"] = [
        {
            "style": [
                {
                    "value": style,
                    "language_tag": "en_US",
                    "marketplace_id": marketplace_id,
                }
            ],
            "marketplace_id": marketplace_id,
        }
    ]


def _extract_door_style(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            if first.get("value"):
                return str(first["value"])
            style = first.get("style")
            if isinstance(style, list) and style:
                item = style[0]
                if isinstance(item, dict) and item.get("value"):
                    return str(item["value"])
    return ""


def _cabinet_door_style(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in _DOOR_STYLES:
        return _DOOR_STYLES[text]
    for key, canonical in _DOOR_STYLES.items():
        if key in text:
            return canonical
    return "Shaker"
