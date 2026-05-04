"""Single-field mapping helpers for Amazon listing data."""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class DataFieldMapper:
    """Maps one Amazon template field from product and raw supplier data."""

    WEIGHT_UNIT_MAP = {
        "lb": "Pounds",
        "kg": "Kilograms",
        "oz": "Ounces",
        "g": "Grams",
    }

    DIMENSION_UNIT_MAP = {
        "in": "Inches",
        "cm": "Centimeters",
        "mm": "Millimeters",
        "ft": "Feet",
    }

    def map_single_field(
        self,
        field_name: str,
        rule: Dict,
        product_data: Dict,
        raw_data: Dict,
        category_map: Optional[Dict],
    ) -> Any:
        """Map a single field based on its configured source type."""
        source_type = rule.get("source_type")

        if source_type == "static":
            return rule.get("value")

        if source_type == "direct":
            value = product_data.get(rule.get("value"))
            if field_name == "Product Type" and isinstance(value, str):
                return value.upper()
            return value

        if source_type == "db_field":
            return product_data.get(rule.get("field"))

        if source_type == "db_field_multiple":
            fields = rule.get("fields", [])
            return [product_data.get(f) for f in fields if product_data.get(f)]

        if source_type == "jsonb":
            value = self.get_jsonb_value(raw_data, rule.get("json_path"))
            if value in (None, "", "Not Applicable"):
                fallback = rule.get("fallback")
                return fallback if fallback is not None else value
            return value

        if source_type == "jsonb_array":
            return raw_data.get(rule.get("json_path"), [])

        if source_type == "jsonb_computed":
            combo_info = raw_data.get(rule.get("json_path"), [])
            return len(combo_info) if combo_info else 1

        if source_type == "package_dimension":
            dim = rule.get("dimension")
            combo_info = raw_data.get("comboInfo", [])
            value = raw_data.get(dim)
            if not value and combo_info:
                value = combo_info[0].get(dim)
            return value

        if source_type == "item_dimension":
            value = raw_data.get(rule.get("dimension"))
            if value == "Not Applicable":
                return None
            return value

        if source_type == "unit_mapper":
            return self.map_unit(rule.get("unit_type"), raw_data)

        if source_type == "summed_weight":
            return self.calculate_weight(rule.get("weight_type"), raw_data)

        if source_type == "category_lookup":
            if not category_map:
                return None
            current_category = product_data.get("category_name", "").upper()
            lookup_key = rule.get("lookup_key")
            if current_category and lookup_key:
                return category_map.get(current_category, {}).get(lookup_key)
            return None

        logger.warning(f"未知的source_type: {source_type} (字段: {field_name})")
        return None

    @staticmethod
    def get_jsonb_value(raw_data: Dict, json_path: str) -> Any:
        """Extract a nested value from JSON-like supplier data."""
        if not json_path:
            return None

        path_keys = json_path.split(".")
        temp_value = raw_data

        for key in path_keys:
            if isinstance(temp_value, dict):
                temp_value = temp_value.get(key)
            else:
                return None

            if temp_value is None:
                break

        return temp_value

    def map_unit(self, unit_type: str, raw_data: Dict) -> Optional[str]:
        """Map supplier units to Amazon template unit labels."""
        if unit_type == "weight":
            raw_unit = raw_data.get("weightUnit")
            return self.WEIGHT_UNIT_MAP.get(str(raw_unit).lower())

        if unit_type == "dimension":
            raw_unit = raw_data.get("lengthUnit")
            return self.DIMENSION_UNIT_MAP.get(str(raw_unit).lower())

        return None

    @staticmethod
    def calculate_weight(weight_type: str, raw_data: Dict) -> Optional[float]:
        """Calculate item or package weight."""
        if weight_type == "item":
            total_weight = raw_data.get("assembledWeight")
        else:
            total_weight = raw_data.get("weight")

        if not total_weight and raw_data.get("comboFlag"):
            combo_info = raw_data.get("comboInfo", [])
            total_weight = sum(item.get("weight", 0) for item in combo_info)

        return total_weight if total_weight else None
