"""Pure helpers for variation theme determination."""
import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def strip_html(html_string: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not html_string:
        return ""
    clean_text = re.sub(r"<[^>]+>", "", html_string)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text


def clean_family_products(family_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build compact product payloads for LLM variation-theme requests."""
    cleaned_products = []

    for product in family_data:
        raw_data = product.get("raw_data", {}) or {}
        dimensions_and_weight = {
            "assembledLength": raw_data.get("assembledLength"),
            "assembledWidth": raw_data.get("assembledWidth"),
            "assembledHeight": raw_data.get("assembledHeight"),
            "weight": raw_data.get("weight"),
        }

        cleaned_products.append({
            "meow_sku": product.get("meow_sku"),
            "name": product.get("product_name"),
            "description": strip_html(
                product.get("product_description") or raw_data.get("description")
            ),
            "attributes": raw_data.get("attributes", {}),
            "dimensions_and_weight": {
                key: value
                for key, value in dimensions_and_weight.items()
                if value is not None
            },
        })

    return cleaned_products


def filter_priority_themes(
    priority_themes: List[str],
    valid_themes: List[str],
) -> List[str]:
    """Keep only configured priority themes that exist in the template."""
    return [
        theme for theme in priority_themes
        if theme in valid_themes
    ] if priority_themes else []


def build_first_round_prompt(
    family_data: List[Dict[str, Any]],
    valid_themes: List[str],
    priority_themes: List[str],
) -> str:
    """Build JSON user prompt for first-round variation-theme detection."""
    user_content = {
        "high_priority_themes": filter_priority_themes(priority_themes, valid_themes),
        "valid_variation_themes": valid_themes,
        "products": clean_family_products(family_data),
    }
    return json.dumps(user_content, indent=2, ensure_ascii=False)


def build_correction_prompt(
    family_data: List[Dict[str, Any]],
    valid_themes: List[str],
    priority_themes: List[str],
    failed_theme: str,
) -> str:
    """Build JSON user prompt for duplicate-attribute correction."""
    user_content = {
        "failed_theme": failed_theme,
        "valid_variation_themes": valid_themes,
        "recommended_themes": filter_priority_themes(priority_themes, valid_themes),
        "products": clean_family_products(family_data),
    }
    return json.dumps(user_content, indent=2, ensure_ascii=False)


def check_attribute_uniqueness(child_attributes: Dict[str, Dict]) -> bool:
    """Return whether all variation attribute combinations are unique."""
    if not child_attributes:
        return True

    seen_signatures = set()

    for attributes in child_attributes.values():
        attr_signature = "|".join(
            f"{key}:{value}" for key, value in sorted(attributes.items())
        )

        if attr_signature in seen_signatures:
            logger.warning(f"检测到重复属性组合: {attr_signature}")
            return False

        seen_signatures.add(attr_signature)

    return True


def format_variation_attributes(
    child_attributes: Dict[str, Dict],
) -> Dict[str, Dict]:
    """Format variation attributes, including rounding numeric size values."""
    formatted = {}

    for sku, attributes in child_attributes.items():
        new_attributes = {}

        for key, value in attributes.items():
            if "size" in key.lower() and isinstance(value, (int, float, str)):
                try:
                    rounded_value = int(round(float(value)))
                    new_attributes[key] = str(rounded_value)
                except (ValueError, TypeError):
                    new_attributes[key] = value
            else:
                new_attributes[key] = value

        formatted[sku] = new_attributes

    return formatted
