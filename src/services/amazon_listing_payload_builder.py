"""Render AmazonListingDraft objects directly to SP-API attributes."""

from difflib import get_close_matches
from typing import Any, Dict, List, Optional

from infrastructure.amazon.config import AmazonConfig
from src.models.amazon_listing import AmazonListingDraft
from src.models.product import DimensionSpec, StandardProduct


class AmazonListingPayloadBuilder:
    """Schema-aware builder for Listings Items API payload plans."""

    _COUNTRY_TO_ISO = {
        "china": "CN",
        "cn": "CN",
        "united states": "US",
        "usa": "US",
        "us": "US",
        "vietnam": "VN",
        "viet nam": "VN",
        "india": "IN",
        "mexico": "MX",
        "canada": "CA",
    }

    def __init__(
        self,
        schema_service: Any = None,
        marketplace_id: Optional[str] = None,
    ):
        self.schema_service = schema_service
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID

    def build_plan(self, draft: AmazonListingDraft) -> Dict[str, Any]:
        """Build {"sku", "product_type", "attributes"} for submitter."""
        attrs: Dict[str, Any] = {}
        product = draft.standard_product

        self._set_text(attrs, "item_name", draft.content.title)
        self._set_text(attrs, "product_description", draft.content.description)
        self._set_list(attrs, "bullet_point", draft.content.bullets)
        self._set_text(attrs, "brand", "Generic")
        self._set_text(attrs, "manufacturer", "Nova Home Essentials")
        self._set_text(attrs, "part_number", self._attr(product, "mpn") or draft.vendor_sku)
        self._set_text(attrs, "model_number", self._attr(product, "mpn") or draft.vendor_sku)
        self._set_text(attrs, "item_type_keyword", draft.product_type.lower())
        self._set_text(attrs, "item_type_name", draft.product_type.replace("_", " ").title())
        self._set_text(attrs, "target_audience_base", "Homeowners")
        self._set_text(attrs, "condition_type", draft.offer.condition_type)

        color = self._attr(product, "Main Color", "color")
        material = self._attr(product, "Main Material", "material")
        style = self._attr(product, "Product Style", "style")
        self._set_list(attrs, "color", [self._valid_value(draft.product_type, "color", color)])
        self._set_list(attrs, "material", [material])
        self._set_text(attrs, "style", style)

        country = self._country_code(self._attr(product, "place_of_origin") or "China")
        self._set_text(
            attrs,
            "country_of_origin",
            self._valid_value(draft.product_type, "country_of_origin", country),
        )

        self._set_images(attrs, product.images)
        self._set_offer(attrs, draft.offer.price, draft.offer.currency)
        self._set_quantity(attrs, draft.offer.quantity)
        self._set_dimensions(attrs, draft.product_type, product.dimensions)

        if draft.variation.parentage_level:
            self._set_text(attrs, "parentage_level", draft.variation.parentage_level.lower())
        if draft.variation.variation_theme:
            attrs["variation_theme"] = [{"name": draft.variation.variation_theme}]
        if draft.variation.parent_sku:
            attrs["child_parent_sku_relationship"] = [
                {
                    "child_relationship_type": (
                        draft.variation.child_relationship_type or "Variation"
                    ),
                    "parent_sku": draft.variation.parent_sku,
                }
            ]
        for key, value in draft.variation.theme_attributes.items():
            attr_name = self._variation_attribute_name(key)
            self._set_list(
                attrs,
                attr_name,
                [self._valid_value(draft.product_type, attr_name, value)],
            )

        self._add_required_defaults(attrs)

        return {
            "sku": draft.sku,
            "product_type": draft.product_type,
            "attributes": attrs,
        }

    def _set_text(self, attrs: Dict[str, Any], name: str, value: Any) -> None:
        text = str(value or "").strip()
        if text:
            attrs[name] = [{"value": text}]

    def _set_list(self, attrs: Dict[str, Any], name: str, values: List[Any]) -> None:
        cleaned = [str(value or "").strip() for value in values if str(value or "").strip()]
        if cleaned:
            attrs[name] = [{"value": value} for value in cleaned]

    def _set_images(self, attrs: Dict[str, Any], images: List[str]) -> None:
        urls = [str(url or "").strip() for url in images if str(url or "").strip()]
        if not urls:
            return
        attrs["main_product_image_locator"] = [{"media_location": urls[0]}]
        for idx, url in enumerate(urls[1:9], start=1):
            attrs[f"other_product_image_locator_{idx}"] = [{"media_location": url}]

    def _set_offer(
        self,
        attrs: Dict[str, Any],
        price: Optional[float],
        currency: str,
    ) -> None:
        if price is None:
            return
        attrs["purchasable_offer"] = [
            {
                "currency": currency or "USD",
                "our_price": [{"schedule": [{"value_with_tax": float(price)}]}],
                "marketplace_id": self.marketplace_id,
            }
        ]
        attrs["list_price"] = [{"currency": currency or "USD", "value": float(price)}]

    def _set_quantity(self, attrs: Dict[str, Any], quantity: int) -> None:
        if quantity < 0:
            quantity = 0
        attrs["fulfillment_availability"] = [
            {
                "fulfillment_channel_code": "DEFAULT",
                "quantity": int(quantity),
            }
        ]

    def _set_dimensions(
        self,
        attrs: Dict[str, Any],
        product_type: str,
        dimensions: Optional[DimensionSpec],
    ) -> None:
        if dimensions is None:
            return

        width = dimensions.assembled_length or dimensions.length
        depth = dimensions.assembled_width or dimensions.width
        height = dimensions.assembled_height or dimensions.height
        if product_type.upper() == "CABINET" and width and depth and height:
            attrs["item_depth_width_height"] = [
                {
                    "depth": {"value": float(depth), "unit": "inches"},
                    "width": {"value": float(width), "unit": "inches"},
                    "height": {"value": float(height), "unit": "inches"},
                }
            ]
        else:
            self._set_measure(attrs, "item_width", width, "inches")
            self._set_measure(attrs, "item_depth", depth, "inches")
            self._set_measure(attrs, "item_height", height, "inches")

        weight = dimensions.assembled_weight or dimensions.weight
        self._set_measure(attrs, "item_weight", weight, "pounds")

    @staticmethod
    def _set_measure(
        attrs: Dict[str, Any],
        name: str,
        value: Any,
        unit: str,
    ) -> None:
        if value is None or value == "":
            return
        attrs[name] = [{"value": float(value), "unit": unit}]

    def _valid_value(self, product_type: str, field_name: str, value: Any) -> str:
        text = str(value or "").strip()
        if not text or self.schema_service is None:
            return text
        try:
            if hasattr(self.schema_service, "get_cached_valid_values"):
                candidates = self.schema_service.get_cached_valid_values(
                    product_type, field_name
                )
            else:
                candidates = self.schema_service.get_valid_values(product_type, field_name)
        except Exception:
            return text
        if not candidates:
            return text
        exact = {str(item).lower(): str(item) for item in candidates}
        if text.lower() in exact:
            return exact[text.lower()]
        match = get_close_matches(text.lower(), list(exact.keys()), n=1, cutoff=0.85)
        return exact[match[0]] if match else text

    @classmethod
    def _country_code(cls, value: str) -> str:
        return cls._COUNTRY_TO_ISO.get(str(value or "").strip().lower(), value)

    @staticmethod
    def _attr(product: StandardProduct, *names: str) -> str:
        lowered = {key.lower(): value for key, value in product.attributes.items()}
        for name in names:
            value = product.attributes.get(name)
            if value:
                return str(value)
            value = lowered.get(name.lower())
            if value:
                return str(value)
        return ""

    @staticmethod
    def _variation_attribute_name(name: str) -> str:
        mapping = {
            "color_name": "color",
            "colour_name": "color",
            "size_name": "size_name",
            "material_name": "material",
        }
        return mapping.get(name, name)

    @staticmethod
    def _add_required_defaults(attrs: Dict[str, Any]) -> None:
        defaults = {
            "supplier_declared_dg_hz_regulation": [{"value": "not_applicable"}],
            "externally_assigned_product_identifier": [
                {"type": "GTIN_EXEMPTION", "value": "product_does_not_have_gtin"}
            ],
            "supplier_declared_has_product_identifier_exemption": [{"value": "Yes"}],
        }
        for key, value in defaults.items():
            attrs.setdefault(key, value)
