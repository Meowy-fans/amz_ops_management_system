"""Transforms Excel-format listing rows into SP-API JSON attributes."""
import json
import os
from typing import Any, Dict, List, Optional

# Sentinel for _convert dispatcher chain
_NOT_FOUND = object()


class AmazonAttributeMapper:
    """Converts flat mapped rows (Amazon Excel field names) into nested SP-API
    JSON attribute payloads for putListingsItem.

    Loads mapping configuration from
    config/amz_listing_data_mapping/sp_api_common.json and optional
    product-type-specific overrides.
    """

    def __init__(self, product_type: str, marketplace_id: str = "ATVPDKIKX0DER"):
        self.product_type = product_type
        self.marketplace_id = marketplace_id
        self._mapping_config = self._load_config(product_type)

    # ── public API ────────────────────────────────────────────────

    def map_rows_to_plans(
        self, rows: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert every row into a listing submission plan."""
        plans: List[Dict[str, Any]] = []
        for row in rows:
            sku = row.get("SKU", "")
            if not sku:
                continue
            attributes = self._row_to_attributes(row)
            self._add_required_defaults(attributes)
            plans.append(
                {
                    "sku": sku,
                    "product_type": self.product_type,
                    "attributes": attributes,
                }
            )
        return plans

    def _add_required_defaults(self, attributes: Dict[str, Any]) -> None:
        """Ensure minimum required fields are present."""
        defaults = {
            "supplier_declared_dg_hz_regulation": [{"value": "not_applicable"}],
            "externally_assigned_product_identifier": [
                {"type": "GTIN_EXEMPTION", "value": "product_does_not_have_gtin"}
            ],
            "supplier_declared_has_product_identifier_exemption": [{"value": "Yes"}],
        }
        for key, default_val in defaults.items():
            if key not in attributes:
                attributes[key] = default_val

    # ── internal ──────────────────────────────────────────────────

    @classmethod
    def _load_config(cls, product_type: str) -> Dict[str, Any]:
        base_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "config",
            "amz_listing_data_mapping",
        )
        common_path = os.path.join(base_dir, "sp_api_common.json")
        mappings: Dict[str, Any] = {}
        if os.path.exists(common_path):
            with open(common_path) as f:
                mappings = json.load(f).get("mappings", {})

        override_path = os.path.join(base_dir, f"sp_api_{product_type.lower()}.json")
        if os.path.exists(override_path):
            with open(override_path) as f:
                overrides = json.load(f).get("mappings", {})
                mappings.update(overrides)

        return mappings

    def _row_to_attributes(self, row: Dict[str, Any]) -> Dict[str, Any]:
        attributes: Dict[str, Any] = {}
        dim_collector: Dict[str, float] = {}

        for excel_field_name, value in row.items():
            mapping = self._mapping_config.get(excel_field_name)
            if mapping is None:
                continue

            attr_type = mapping["type"]
            path = mapping["path"]

            if attr_type == "skip":
                continue

            if value is None or value == "" or value == "Not Applicable":
                continue

            new_val = self._convert(value, attr_type)
            if new_val is None:
                continue

            # Collect dimensions for combined item_depth_width_height
            if attr_type in ("cabinet_dim_depth", "ottoman_dim_depth"):
                dim_collector["depth"] = new_val
                continue
            if attr_type in ("cabinet_dim_width", "ottoman_dim_width"):
                dim_collector["width"] = new_val
                continue
            if attr_type in ("cabinet_dim_height", "ottoman_dim_height"):
                dim_collector["height"] = new_val
                continue

            self._set_nested(attributes, path, new_val)

        # Post-process: combine cabinet dimensions
        if len(dim_collector) == 3:
            attributes["item_depth_width_height"] = [
                {
                    "depth": {
                        "value": dim_collector["depth"],
                        "unit": "inches",
                    },
                    "width": {
                        "value": dim_collector["width"],
                        "unit": "inches",
                    },
                    "height": {
                        "value": dim_collector["height"],
                        "unit": "inches",
                    },
                }
            ]

        # Post-process: build child-parent SKU relationship for variation children
        parent_sku_data = attributes.pop("_parent_sku", None)
        parentage = attributes.get("parentage_level", [])
        is_child = parentage and parentage[0].get("value") == "child"

        if is_child and parent_sku_data:
            parent_sku_val = parent_sku_data[0].get("value", "")
            if parent_sku_val:
                attributes["child_parent_sku_relationship"] = [
                    {
                        "child_relationship_type": "Variation",
                        "parent_sku": parent_sku_val,
                    }
                ]

        return attributes

    def _convert(self, value: Any, attr_type: str) -> Any:
        for handler in (
            self._convert_text,
            self._convert_image,
            self._convert_price,
            self._convert_numeric,
            self._convert_special,
        ):
            result = handler(value, attr_type)
            if result is not _NOT_FOUND:
                return result
        return None

    def _convert_text(self, value: Any, attr_type: str) -> Any:
        if attr_type in ("text", "list", "text_list", "country", "parentage"):
            return self.__convert_text(value, attr_type)
        return _NOT_FOUND

    def __convert_text(self, value: Any, attr_type: str) -> Any:
        if attr_type == "text":
            v = value[0] if isinstance(value, list) else value
            return [{"value": str(v).strip()}] if v else None
        if attr_type == "country":
            val = value[0] if isinstance(value, list) else str(value)
            iso = AmazonAttributeMapper._country_to_iso(val.strip())
            return [{"value": iso}]
        if attr_type == "list":
            items = value if isinstance(value, list) else [value]
            return [{"value": str(v).strip()} for v in items if v]
        if attr_type == "text_list":
            items = value if isinstance(value, list) else [str(value)]
            return [{"value": str(v).strip()} for v in items if v]
        if attr_type == "parentage":
            text = value[0] if isinstance(value, list) else str(value)
            return [{"value": text.strip().lower()}]
        return _NOT_FOUND

    def _convert_image(self, value: Any, attr_type: str) -> Any:
        if attr_type in ("image", "image_single"):
            url = value[0] if isinstance(value, list) else value
            return [{"media_location": str(url)}] if url else None
        if attr_type == "image_list":
            urls = value if isinstance(value, list) else [value]
            result = [{"media_location": str(u)} for u in urls if u]
            return result or None
        return _NOT_FOUND

    def _convert_price(self, value: Any, attr_type: str) -> Any:
        if attr_type == "price":
            num = self._to_float(value)
            if num is None:
                return None
            return [{"currency": "USD", "our_price": [
                {"schedule": [{"value_with_tax": num}]}],
                     "marketplace_id": self.marketplace_id}]
        if attr_type == "list_price":
            num = self._to_float(value)
            return [{"currency": "USD", "value": num}] if num is not None else None
        return _NOT_FOUND

    def _convert_numeric(self, value: Any, attr_type: str) -> Any:
        if attr_type == "quantity":
            num = self._to_int(value)
            if num is None:
                return None
            return [{"fulfillment_channel_code": "DEFAULT", "quantity": num}]
        if attr_type == "dimension":
            num = self._to_float(value)
            return [{"value": num, "unit": "inches"}] if num is not None else None
        if attr_type in ("cabinet_dim_depth", "cabinet_dim_width", "cabinet_dim_height",
                         "ottoman_dim_depth", "ottoman_dim_width", "ottoman_dim_height"):
            return self._to_float(value)
        if attr_type == "weight":
            num = self._to_float(value)
            return [{"value": num, "unit": "pounds"}] if num is not None else None
        if attr_type == "number":
            num = self._to_int(value)
            return [{"value": num}] if num is not None else None
        return _NOT_FOUND

    def _convert_special(self, value: Any, attr_type: str) -> Any:
        if attr_type == "cabinet_door":
            text = value[0] if isinstance(value, list) else str(value)
            return [{"style": [{"value": text.strip()}]}]
        if attr_type == "variation_theme_ottoman":
            text = value[0] if isinstance(value, list) else str(value)
            return [{"name": text.strip()}]
        return _NOT_FOUND

    _COUNTRY_TO_ISO = {
        "china": "CN",
        "vietnam": "VN",
        "viet nam": "VN",
        "united states": "US",
        "usa": "US",
        "india": "IN",
        "mexico": "MX",
        "canada": "CA",
        "germany": "DE",
        "italy": "IT",
        "japan": "JP",
        "korea": "KR",
        "taiwan": "TW",
        "thailand": "TH",
        "malaysia": "MY",
        "indonesia": "ID",
        "brazil": "BR",
        "turkey": "TR",
        "united kingdom": "GB",
        "uk": "GB",
        "france": "FR",
    }

    @classmethod
    def _country_to_iso(cls, name: str) -> str:
        return cls._COUNTRY_TO_ISO.get(name.lower(), name[:2].upper())

    @staticmethod
    def _set_nested(target: Dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        current = target
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if isinstance(value, list):
                value = value[0] if value else None
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        try:
            if isinstance(value, list):
                value = value[0] if value else None
            if value is None:
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None
