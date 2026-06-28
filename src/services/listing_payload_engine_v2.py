"""Read-only orchestration for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

from typing import Any, Dict

from infrastructure.amazon.config import AmazonConfig
from sqlalchemy.orm import Session

from src.models.product import DimensionSpec, StandardProduct
from src.repositories.product_data_repository import ProductDataRepository
from src.services.amazon_listing_draft_builder import AmazonListingDraftBuilder
from src.services.amazon_schema_service import AmazonSchemaService
from src.services.confidence_scorer_v2 import ConfidenceScorerV2
from src.services.coverage_gate_v2 import CoverageGateV2
from src.services.evidence_resolver_v2 import EvidenceResolverV2
from src.services.llm_attribute_extractor_v2 import LLMAttributeExtractorV2
from src.services.optional_rule_children_enricher_v2 import OptionalRuleChildrenEnricherV2
from src.services.payload_composer_v2 import PayloadComposerV2
from src.services.amazon_listing_variation_payload import (
    render_variation_attribute,
    variation_theme_name,
)
from src.services.requirement_models_v2 import PayloadBuildPlan, RequirementNode, ResolutionNode
from src.services.requirement_tree_builder_v2 import RequirementTreeBuilderV2


class ListingPayloadEngineV2:
    """Coordinates V2 read-only requirement analysis."""

    def __init__(
        self,
        db: Session,
        schema_service: AmazonSchemaService | None = None,
        product_repo: ProductDataRepository | None = None,
        draft_builder: AmazonListingDraftBuilder | None = None,
        llm_extractor: Any = None,
        confidence_scorer: Any = None,
    ):
        self.db = db
        self.schema_service = schema_service or AmazonSchemaService(db)
        self.product_repo = product_repo or ProductDataRepository(db)
        self.draft_builder = draft_builder or AmazonListingDraftBuilder()
        self.llm_extractor = llm_extractor or LLMAttributeExtractorV2()
        self.confidence_scorer = confidence_scorer or ConfidenceScorerV2(
            schema_service=self.schema_service
        )

    def analyze_requirements(self, product_type: str, sku: str) -> Dict[str, Any]:
        """Return a read-only requirement tree analysis for one SKU."""
        product_data = self.product_repo.get_full_product_data(sku)
        if not product_data:
            raise ValueError(f"SKU not found: {sku}")
        draft = self.draft_builder.build(product_data, product_type=product_type)
        candidate_attributes = self._candidate_attributes_from_draft(draft)
        tree = RequirementTreeBuilderV2(self.schema_service).build(
            product_type=product_type,
            attributes=candidate_attributes,
        )
        return {
            "sku": sku,
            "product_type": str(product_type or "").strip().upper(),
            "candidate_attribute_names": sorted(candidate_attributes),
            "requirement_tree": tree.as_dict(),
        }

    def build_read_only_plan(
        self,
        product_type: str,
        sku: str,
        rules: Dict[str, Any],
        overrides: Dict[str, Any] | None = None,
    ) -> PayloadBuildPlan:
        """Build a V2 plan without submitting or changing V1 behavior."""
        product_data = self.product_repo.get_full_product_data(sku)
        if not product_data:
            raise ValueError(f"SKU not found: {sku}")
        normalized = str(product_type or "").strip().upper()
        draft = self.draft_builder.build(product_data, product_type=normalized)
        return self.build_read_only_plan_from_draft(
            draft=draft,
            rules=rules,
            overrides=overrides,
        )

    def build_read_only_plan_from_draft(
        self,
        draft,
        rules: Dict[str, Any],
        overrides: Dict[str, Any] | None = None,
    ) -> PayloadBuildPlan:
        """Build a V2 plan from an already prepared draft.

        Plan builder integrations use this path to preserve upstream commercial,
        image, and variation decisions instead of rebuilding a plain SKU draft.
        """
        normalized = str(draft.product_type or "").strip().upper()
        draft.product_type = normalized
        candidate_attributes = self._candidate_attributes_from_draft(draft, rules)
        requirement_tree = RequirementTreeBuilderV2(self.schema_service).build(
            product_type=normalized,
            attributes=candidate_attributes,
        )
        resolution_tree = EvidenceResolverV2(
            self.schema_service,
            llm_extractor=self.llm_extractor,
        ).resolve(
            requirement_tree.root,
            draft,
            rules,
            overrides,
            candidate_attributes,
        )
        self.confidence_scorer.score_tree(resolution_tree, draft, requirement_tree.root)
        self._apply_review_routing(resolution_tree, requirement_tree.root)
        attributes = PayloadComposerV2().compose(requirement_tree.root, resolution_tree)
        attributes = self._merge_candidate_attributes(
            product_type=normalized,
            attributes=attributes,
            candidate_attributes=candidate_attributes,
        )
        attributes = OptionalRuleChildrenEnricherV2().enrich(
            attributes=attributes,
            rules=rules,
            requirement_root=requirement_tree.root,
            draft=draft,
            resolver=EvidenceResolverV2(
                self.schema_service,
                llm_extractor=self.llm_extractor,
            ),
            candidate_attributes=candidate_attributes,
        )
        attributes = OptionalRuleChildrenEnricherV2.strip_incomplete_ignored_attributes(
            attributes,
            rules.get("coverage_ignore_required") or [],
        )
        self._apply_rule_shape_parity(attributes, draft, rules)
        self._apply_post_processors(attributes, rules)
        coverage_gate = CoverageGateV2(
            ignored_required_paths=rules.get("coverage_ignore_required") or []
        )
        coverage = coverage_gate.evaluate(
            requirement_tree.root,
            resolution_tree,
            attributes,
        )
        plan = PayloadBuildPlan(
            sku=draft.sku,
            product_type=normalized,
            attributes=attributes,
            requirement_tree=requirement_tree,
            resolution_tree=resolution_tree,
        )
        return CoverageGateV2.apply_to_plan(plan, coverage)

    def _merge_candidate_attributes(
        self,
        product_type: str,
        attributes: Dict[str, Any],
        candidate_attributes: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add schema-allowed deterministic non-required attributes.

        RequirementTree drives required coverage, but Listings payloads still
        need deterministic optional/core fields such as images, offers, and
        variation attributes. Requirement-derived values win on conflicts.
        """
        allowed = self._schema_property_names(product_type)
        merged = dict(attributes)
        for name, value in candidate_attributes.items():
            if name in merged or value in (None, "", []):
                continue
            if allowed and name not in allowed:
                continue
            merged[name] = value
        return merged

    def _apply_rule_shape_parity(
        self,
        attributes: Dict[str, Any],
        draft,
        rules: Dict[str, Any],
    ) -> None:
        """Align selected universal rule attributes with proven V1 SP-API shapes."""
        from src.services.attribute_payload_renderer import AttributePayloadRenderer
        from src.services.attribute_resolver import AttributeResolver

        parity_keys = {
            "externally_assigned_product_identifier",
            "supplier_declared_has_product_identifier_exemption",
        }
        rendered = AttributePayloadRenderer().render(
            AttributeResolver().resolve(draft, rules)
        )
        allowed = self._schema_property_names(str(draft.product_type or "").strip().upper())
        for key in parity_keys:
            value = rendered.get(key)
            if value in (None, "", []):
                continue
            if allowed and key not in allowed:
                continue
            attributes[key] = value

    def _apply_post_processors(
        self,
        attributes: Dict[str, Any],
        rules: Dict[str, Any],
    ) -> None:
        from src.services.attribute_post_processors import apply_attribute_post_processors

        apply_attribute_post_processors(
            rules.get("post_processors") or [],
            attributes,
            AmazonConfig.MARKETPLACE_ID,
        )

    def _schema_property_names(self, product_type: str) -> set[str]:
        if self.schema_service is None:
            return set()
        try:
            schema = self.schema_service.get_or_fetch_schema(product_type) or {}
        except Exception:
            return set()
        schema_json = schema.get("schema_json") or {}
        properties = schema_json.get("properties") or {}
        return {str(name) for name in properties}

    def _candidate_attributes_from_draft(
        self,
        draft,
        rules: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {}
        product = draft.standard_product
        self._set_text(attrs, "item_name", draft.content.title)
        self._set_text(attrs, "product_description", draft.content.description)
        self._set_list(attrs, "bullet_point", draft.content.bullets)
        self._set_text(attrs, "part_number", self._attr(product, "mpn") or draft.vendor_sku)
        self._set_text(attrs, "model_number", self._attr(product, "mpn") or draft.vendor_sku)
        self._set_text(attrs, "condition_type", draft.offer.condition_type)
        self._set_images(attrs, product.images)
        color = self._attr(product, "Main Color", "color")
        material = self._attr(product, "Main Material", "material")
        self._set_list(
            attrs,
            "color",
            [self._valid_value(draft.product_type, "color", color)],
        )
        self._set_list(attrs, "material", [material])
        if draft.offer.price is not None:
            attrs["list_price"] = [
                {"currency": draft.offer.currency or "USD", "value": float(draft.offer.price)}
            ]
            attrs["purchasable_offer"] = [
                {
                    "currency": draft.offer.currency or "USD",
                    "marketplace_id": AmazonConfig.MARKETPLACE_ID,
                    "our_price": [{"schedule": [{"value_with_tax": float(draft.offer.price)}]}],
                }
            ]
        attrs["fulfillment_availability"] = [
            {
                "fulfillment_channel_code": "DEFAULT",
                "quantity": max(int(draft.offer.quantity or 0), 0),
            }
        ]
        self._set_dimensions(attrs, draft.product_type, product.dimensions, rules or {})
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
                    "parent_sku": draft.variation.parent_sku,
                    "child_relationship_type": (
                        draft.variation.child_relationship_type or "Variation"
                    ),
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
        return attrs

    @staticmethod
    def _set_text(attrs: Dict[str, Any], name: str, value: Any) -> None:
        text = str(value or "").strip()
        if text:
            attrs[name] = [{"value": text}]

    @staticmethod
    def _set_list(attrs: Dict[str, Any], name: str, values: list[Any]) -> None:
        cleaned = [str(value or "").strip() for value in values if str(value or "").strip()]
        if cleaned:
            attrs[name] = [{"value": item} for item in cleaned]

    @staticmethod
    def _set_images(attrs: Dict[str, Any], images: list[str]) -> None:
        urls = [str(url or "").strip() for url in images if str(url or "").strip()]
        if not urls:
            return
        attrs["main_product_image_locator"] = [{"media_location": urls[0]}]
        for idx, url in enumerate(urls[1:9], start=1):
            attrs[f"other_product_image_locator_{idx}"] = [{"media_location": url}]

    def _set_dimensions(
        self,
        attrs: Dict[str, Any],
        product_type: str,
        dimensions: DimensionSpec | None,
        rules: Dict[str, Any],
    ) -> None:
        if dimensions is None:
            return
        width = dimensions.assembled_length or dimensions.length
        depth = dimensions.assembled_width or dimensions.width
        height = dimensions.assembled_height or dimensions.height
        strategy = str(rules.get("dimension_strategy") or "separate_measures")
        if strategy == "item_depth_width_height" and width and depth and height:
            attrs["item_depth_width_height"] = [
                {
                    "depth": {"value": float(depth), "unit": "inches"},
                    "width": {"value": float(width), "unit": "inches"},
                    "height": {"value": float(height), "unit": "inches"},
                }
            ]
        elif strategy == "item_length_width_height" and width and depth and height:
            length = dimensions.assembled_length or dimensions.length
            if length:
                attrs["item_length_width_height"] = [
                    {
                        "length": {"value": float(length), "unit": "inches"},
                        "width": {"value": float(depth), "unit": "inches"},
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

        values = {
            "item_width": width,
            "item_depth": depth,
            "item_height": height,
        }
        for name in rules.get("additional_dimension_measures") or []:
            if str(name) in values:
                self._set_measure(attrs, str(name), values[str(name)], "inches")

        weight = dimensions.assembled_weight or dimensions.weight
        self._set_measure(attrs, "item_weight", weight, "pounds")

    @staticmethod
    def _set_measure(attrs: Dict[str, Any], name: str, value: Any, unit: str) -> None:
        if value is None or value == "":
            return
        attrs[name] = [{"value": float(value), "unit": unit}]

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

    def _valid_value(self, product_type: str, field_name: str, value: Any) -> str:
        text = str(value or "").strip()
        if not text or self.schema_service is None:
            return text
        try:
            candidates = self.schema_service.get_cached_valid_values(
                product_type,
                field_name,
            )
        except Exception:
            candidates = []
        if not candidates:
            return text
        exact = {str(item).lower(): str(item) for item in candidates}
        if text.lower() in exact:
            return exact[text.lower()]
        return text

    def _apply_review_routing(
        self,
        resolution_root: ResolutionNode,
        requirement_root: RequirementNode,
    ) -> None:
        for resolution, requirement in self._walk_aligned(resolution_root, requirement_root):
            if not self._requires_llm_review(resolution, requirement):
                if (
                    requirement.required
                    and not resolution.children
                    and resolution.review_route == "auto_approved"
                    and not resolution.blocking
                ):
                    resolution.review_status = "auto_approved"
                continue
            resolution.review_status = "pending"
            resolution.blocking = True
            if "NEEDS_REVIEW_REQUIRED_ATTRIBUTE" not in resolution.blocking_codes:
                resolution.blocking_codes.append("NEEDS_REVIEW_REQUIRED_ATTRIBUTE")

    @staticmethod
    def _requires_llm_review(
        resolution: ResolutionNode,
        requirement: RequirementNode,
    ) -> bool:
        if not requirement.required or resolution.children:
            return False
        if resolution.value in (None, ""):
            return False
        if resolution.source != "llm":
            return False
        return resolution.review_route in {"ai_agent", "human"}

    def _walk_aligned(
        self,
        resolution: ResolutionNode,
        requirement: RequirementNode,
    ) -> list[tuple[ResolutionNode, RequirementNode]]:
        pairs = [(resolution, requirement)]
        requirement_children = {child.path_key: child for child in requirement.children}
        for child_resolution in resolution.children:
            child_requirement = requirement_children.get(child_resolution.path_key)
            if child_requirement is None:
                continue
            pairs.extend(self._walk_aligned(child_resolution, child_requirement))
        return pairs
