"""Variation attribute rendering helpers for Listings Items payloads."""
from typing import Any, Callable, Dict, List, Optional


ValidValueFn = Callable[[str, str, Any], str]


def variation_theme_name(
    product_type: str,
    value: Any,
    valid_value: ValidValueFn,
) -> str:
    """Return Amazon-valid variation theme name where deterministic."""
    text = str(value or "").strip()
    aligned = valid_value(product_type, "variation_theme", text)
    if aligned != text:
        return aligned
    normalized = text.upper().replace(" ", "_")
    if product_type.upper() == "CABINET":
        if normalized in {"COLOR/SIZE", "COLOR_NAME/SIZE_NAME"}:
            return "COLOR/ITEM_WIDTH"
        if normalized in {"SIZE", "SIZE_NAME"}:
            return "ITEM_WIDTH"
        if normalized == "COLOR":
            return "COLOR"
    if normalized in {"COLOR", "SIZE", "COLOR/SIZE"}:
        return normalized
    return text


def render_variation_attribute(
    attrs: Dict[str, Any],
    product_type: str,
    key: str,
    value: Any,
    valid_value: ValidValueFn,
) -> None:
    """Render one variation theme attribute into SP-API payload shape."""
    if product_type.upper() == "CABINET" and key == "size_name":
        number = _to_float_or_none(value)
        if number is not None:
            attrs["item_width"] = [{"value": number, "unit": "inches"}]
        return
    attr_name = variation_attribute_name(key)
    cleaned = str(valid_value(product_type, attr_name, value) or "").strip()
    if cleaned:
        attrs[attr_name] = [{"value": cleaned}]


def variation_attribute_name(name: str) -> str:
    mapping = {
        "color_name": "color",
        "colour_name": "color",
        "size_name": "size_name",
        "material_name": "material",
    }
    return mapping.get(name, name)


def _to_float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
