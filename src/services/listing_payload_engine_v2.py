"""Read-only orchestration for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from src.repositories.product_data_repository import ProductDataRepository
from src.services.amazon_listing_draft_builder import AmazonListingDraftBuilder
from src.services.amazon_schema_service import AmazonSchemaService
from src.services.coverage_gate_v2 import CoverageGateV2
from src.services.evidence_resolver_v2 import EvidenceResolverV2
from src.services.payload_composer_v2 import PayloadComposerV2
from src.services.requirement_models_v2 import PayloadBuildPlan
from src.services.requirement_tree_builder_v2 import RequirementTreeBuilderV2


class ListingPayloadEngineV2:
    """Coordinates V2 read-only requirement analysis."""

    def __init__(
        self,
        db: Session,
        schema_service: AmazonSchemaService | None = None,
        product_repo: ProductDataRepository | None = None,
        draft_builder: AmazonListingDraftBuilder | None = None,
    ):
        self.db = db
        self.schema_service = schema_service or AmazonSchemaService(db)
        self.product_repo = product_repo or ProductDataRepository(db)
        self.draft_builder = draft_builder or AmazonListingDraftBuilder()

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
        candidate_attributes = self._candidate_attributes_from_draft(draft)
        requirement_tree = RequirementTreeBuilderV2(self.schema_service).build(
            product_type=normalized,
            attributes=candidate_attributes,
        )
        resolution_tree = EvidenceResolverV2(self.schema_service).resolve(
            requirement_tree.root,
            draft,
            rules,
            overrides,
        )
        attributes = PayloadComposerV2().compose(requirement_tree.root, resolution_tree)
        coverage = CoverageGateV2().evaluate(
            requirement_tree.root,
            resolution_tree,
            attributes,
        )
        plan = PayloadBuildPlan(
            sku=sku,
            product_type=normalized,
            attributes=attributes,
            requirement_tree=requirement_tree,
            resolution_tree=resolution_tree,
        )
        return CoverageGateV2.apply_to_plan(plan, coverage)

    def _candidate_attributes_from_draft(self, draft) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {}
        self._set_text(attrs, "item_name", draft.content.title)
        self._set_text(attrs, "product_description", draft.content.description)
        self._set_list(attrs, "bullet_point", draft.content.bullets)
        self._set_text(attrs, "part_number", draft.vendor_sku)
        self._set_text(attrs, "model_number", draft.vendor_sku)
        self._set_text(attrs, "condition_type", draft.offer.condition_type)
        if draft.offer.price is not None:
            attrs["list_price"] = [
                {"currency": draft.offer.currency or "USD", "value": float(draft.offer.price)}
            ]
            attrs["purchasable_offer"] = [
                {
                    "currency": draft.offer.currency or "USD",
                    "our_price": [{"schedule": [{"value_with_tax": float(draft.offer.price)}]}],
                }
            ]
        attrs["fulfillment_availability"] = [
            {
                "fulfillment_channel_code": "DEFAULT",
                "quantity": max(int(draft.offer.quantity or 0), 0),
            }
        ]
        if draft.variation.parentage_level:
            self._set_text(attrs, "parentage_level", draft.variation.parentage_level.lower())
        if draft.variation.variation_theme:
            attrs["variation_theme"] = [{"name": draft.variation.variation_theme}]
        if draft.variation.parent_sku:
            attrs["child_parent_sku_relationship"] = [
                {
                    "parent_sku": draft.variation.parent_sku,
                    "child_relationship_type": (
                        draft.variation.child_relationship_type or "Variation"
                    ),
                }
            ]
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
