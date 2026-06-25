"""Render AmazonListingDraft objects directly to SP-API attributes."""

from difflib import get_close_matches
from typing import Any, Dict, List, Optional

from infrastructure.amazon.config import AmazonConfig
from src.models.amazon_listing import AmazonListingDraft
from src.models.product import DimensionSpec, StandardProduct
from src.services.amazon_listing_variation_payload import (
    render_variation_attribute,
    variation_theme_name,
)


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
        "malaysia": "MY",
        "my": "MY",
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
        self._set_text(attrs, "part_number", self._attr(product, "mpn") or draft.vendor_sku)
        self._set_text(attrs, "model_number", self._attr(product, "mpn") or draft.vendor_sku)
        self._set_text(attrs, "condition_type", draft.offer.condition_type)

        color = self._attr(product, "Main Color", "color")
        material = self._attr(product, "Main Material", "material")
        style = self._attr(product, "Product Style", "style")
        self._set_list(attrs, "color", [self._valid_value(draft.product_type, "color", color)])
        self._set_list(attrs, "material", [material])
        self._set_text(attrs, "style", style)

        self._set_images(attrs, product.images)
        self._set_offer(attrs, draft.offer.price, draft.offer.currency)
        self._set_quantity(attrs, draft.offer.quantity)
        self._set_dimensions(attrs, draft.product_type, product.dimensions)

        if draft.variation.parentage_level:
            self._set_text(attrs, "parentage_level", draft.variation.parentage_level.lower())
        if draft.variation.variation_theme:
            attrs["variation_theme"] = [
                {
                    "name": variation_theme_name(
                        draft.product_type,
                        draft.variation.variation_theme,
                        self._valid_value,
                    )
                }
            ]
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
            render_variation_attribute(
                attrs,
                draft.product_type,
                key,
                value,
                self._valid_value,
            )

        attribute_resolutions = self._apply_attribute_rules(attrs, draft)
        self._normalize_product_type_attributes(attrs, draft)
        self._remove_configured_attributes(attrs, draft.product_type)
        attrs = self._filter_schema_allowed_attributes(attrs, draft.product_type)

        return {
            "sku": draft.sku,
            "product_type": draft.product_type,
            "attributes": attrs,
            "attribute_resolutions": attribute_resolutions,
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
        strategy = self._dimension_strategy(product_type)
        if strategy == "item_depth_width_height" and width and depth and height:
            attrs["item_depth_width_height"] = [
                {
                    "depth": {"value": float(depth), "unit": "inches"},
                    "width": {"value": float(width), "unit": "inches"},
                    "height": {"value": float(height), "unit": "inches"},
                }
            ]
        elif strategy == "item_length_width" and width:
            length = height or dimensions.length
            if length:
                attrs["item_length_width"] = [
                    {
                        "length": {"value": float(length), "unit": "inches"},
                        "width": {"value": float(width), "unit": "inches"},
                    }
                ]
        else:
            self._set_measure(attrs, "item_width", width, "inches")
            self._set_measure(attrs, "item_depth", depth, "inches")
            self._set_measure(attrs, "item_height", height, "inches")
        self._set_additional_dimension_measures(
            attrs,
            product_type,
            width=width,
            depth=depth,
            height=height,
        )

        weight = dimensions.assembled_weight or dimensions.weight
        self._set_measure(attrs, "item_weight", weight, "pounds")

    @staticmethod
    def _dimension_strategy(product_type: str) -> str:
        try:
            from src.services.attribute_rule_loader import AttributeRuleLoader

            rules = AttributeRuleLoader().load(product_type)
        except Exception:
            return "separate_measures"
        return str(rules.get("dimension_strategy") or "separate_measures")

    def _set_additional_dimension_measures(
        self,
        attrs: Dict[str, Any],
        product_type: str,
        width: Any,
        depth: Any,
        height: Any,
    ) -> None:
        try:
            from src.services.attribute_rule_loader import AttributeRuleLoader

            rules = AttributeRuleLoader().load(product_type)
        except Exception:
            return
        values = {
            "item_width": width,
            "item_depth": depth,
            "item_height": height,
        }
        for name in rules.get("additional_dimension_measures") or []:
            if str(name) in values:
                self._set_measure(attrs, str(name), values[str(name)], "inches")

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

    def _apply_attribute_rules(
        self,
        attrs: Dict[str, Any],
        draft: AmazonListingDraft,
    ) -> Dict[str, Any]:
        """Merge config-driven resolved attributes into the payload."""
        try:
            from src.services.attribute_payload_renderer import AttributePayloadRenderer
            from src.services.attribute_resolver import AttributeResolver
            from src.services.attribute_rule_loader import AttributeRuleLoader
            from src.services.confidence_scorer import ConfidenceScorer

            resolver = AttributeResolver(
                rule_loader=AttributeRuleLoader(),
                schema_service=self.schema_service,
                confidence_scorer=ConfidenceScorer(schema_service=self.schema_service),
            )
            resolved = resolver.resolve(draft)
            rendered = AttributePayloadRenderer().render(resolved)
        except Exception:
            return {}
        for key, value in rendered.items():
            attrs[key] = value
        return {key: value.as_dict() for key, value in resolved.items()}

    def _filter_schema_allowed_attributes(
        self,
        attrs: Dict[str, Any],
        product_type: str,
    ) -> Dict[str, Any]:
        """Drop attributes that are not accepted by the product type schema."""
        if self.schema_service is None:
            return attrs
        if not hasattr(self.schema_service, "get_property_names"):
            return attrs
        try:
            allowed = self.schema_service.get_property_names(product_type)
        except Exception:
            return attrs
        if not allowed:
            return attrs
        try:
            from src.services.attribute_payload_renderer import AttributePayloadRenderer

            return AttributePayloadRenderer.filter_allowed_attributes(attrs, allowed)
        except Exception:
            return attrs

    def _normalize_product_type_attributes(
        self,
        attrs: Dict[str, Any],
        draft: AmazonListingDraft,
    ) -> None:
        try:
            from src.services.attribute_rule_loader import AttributeRuleLoader

            rules = AttributeRuleLoader().load(draft.product_type)
        except Exception:
            return
        try:
            from src.services.attribute_post_processors import (
                apply_attribute_post_processors,
            )

            apply_attribute_post_processors(
                rules.get("post_processors") or [],
                attrs,
                self.marketplace_id,
            )
        except Exception:
            return

    @staticmethod
    def _remove_configured_attributes(
        attrs: Dict[str, Any],
        product_type: str,
    ) -> None:
        try:
            from src.services.attribute_rule_loader import AttributeRuleLoader

            rules = AttributeRuleLoader().load(product_type)
        except Exception:
            return
        for name in rules.get("remove_attributes") or []:
            attrs.pop(str(name), None)
