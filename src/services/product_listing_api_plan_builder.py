"""Build API-native Amazon listing payload plans."""

import logging
import uuid
from typing import Any, Dict, List, Tuple

from src.services.product_listing_scope import (
    ListingScope,
    ProductListingScopeFilter,
)
from src.services.attribute_review_plan_router import AttributeReviewPlanRouter

logger = logging.getLogger(__name__)


class ProductListingAPIPlanBuilder:
    """Builds Listings Items API plans from normalized product data."""

    def __init__(self, service):
        self.service = service

    def build_for_category(
        self,
        category_name: str,
        scope: ListingScope | None = None,
    ):
        """Build SP-API listing plans without Excel template rows."""
        scope_selection = ProductListingScopeFilter(
            self.service.product_listing_repo,
            listings_client=self._get_listings_client_or_none(scope),
        ).apply(
            category_name,
            scope or ListingScope(),
        )
        pending_skus = scope_selection.selected_skus
        pre_submit_results: List[Dict[str, Any]] = list(
            scope_selection.pre_submit_results
        )
        if not pending_skus and not pre_submit_results:
            raise ValueError(f"品类 '{category_name}' 没有待发品SKU")

        variation_data = self.service.product_listing_repo.get_variation_data(
            pending_skus
        )
        single_skus, variation_families = (
            self.service.variation_helper.find_variation_families(variation_data)
        )
        logger.info(
            "API-native 单品: %d, 变体家族: %d",
            len(single_skus),
            len(variation_families),
        )

        from src.services.amazon_listing_draft_builder import AmazonListingDraftBuilder
        from src.services.amazon_listing_payload_builder import AmazonListingPayloadBuilder

        draft_builder = AmazonListingDraftBuilder()
        payload_builder = AmazonListingPayloadBuilder(
            schema_service=self._get_schema_service_or_none()
        )

        plans: List[Dict[str, Any]] = []
        variation_logs: List[Dict[str, Any]] = []
        for sku in single_skus:
            product_data = self.service.product_data_repo.get_full_product_data(sku)
            if not product_data:
                logger.warning("  跳过SKU %s: 无数据", sku)
                continue
            append_result = self._resolve_existing_parent_append(
                product_data=product_data,
                product_type=category_name,
            )
            commercial_result = self._evaluate_commercial_gate(
                product_data=product_data,
                product_type=category_name,
            )
            if commercial_result.blocked:
                pre_submit_results.append(
                    self._commercial_block_result(sku, commercial_result)
                )
                continue
            product_data = self._with_commercial_publish_quantity(
                product_data,
                commercial_result,
            )
            draft = draft_builder.build(product_data, product_type=category_name)
            self._apply_approved_images(draft)
            if append_result is not None:
                if append_result.decision == "blocked":
                    pre_submit_results.append(
                        self._variation_block_result(sku, append_result)
                    )
                    continue
                from src.models.amazon_listing import ListingVariation

                draft.variation = ListingVariation(
                    parentage_level="child",
                    parent_sku=append_result.parent_sku,
                    variation_theme=append_result.variation_theme,
                    child_relationship_type="Variation",
                    theme_attributes=append_result.child_attributes.get(sku, {}),
                )
                plan = payload_builder.build_plan(draft)
                coverage_result = self._evaluate_attribute_coverage(plan)
                if coverage_result.blocked:
                    pre_submit_results.append(self._coverage_result(sku, plan, coverage_result))
                    continue
                variation_logs.append({
                    "meow_sku": sku,
                    "parent_sku": append_result.parent_sku,
                    "variation_attributes": append_result.child_attributes.get(sku, {}),
                    "listing_batch_id": None,
                    "status": "GENERATED",
                    "variation_theme": append_result.variation_theme,
                })
                plans.append(plan)
                continue
            plan = payload_builder.build_plan(draft)
            coverage_result = self._evaluate_attribute_coverage(plan)
            if coverage_result.blocked:
                pre_submit_results.append(self._coverage_result(sku, plan, coverage_result))
                continue
            plans.append(plan)

        family_plans, family_logs, family_pre_submit_results = (
            self._build_variation_plans(
                variation_families=variation_families,
                category_name=category_name,
                draft_builder=draft_builder,
                payload_builder=payload_builder,
            )
        )
        plans.extend(family_plans)
        variation_logs.extend(family_logs)
        pre_submit_results.extend(family_pre_submit_results)

        if not plans and not pre_submit_results:
            raise ValueError("没有生成任何 API 发品计划")

        logger.info("API-native 总共生成 %d 个发品计划", len(plans))
        return plans, variation_logs, single_skus, variation_families, pre_submit_results

    def _get_listings_client_or_none(self, scope: ListingScope | None):
        if not scope or not scope.only_not_on_amazon:
            return None
        if hasattr(self.service, "_listings_client_instance"):
            return self.service._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self.service._listings_client_instance = AmazonListingsClient()
        return self.service._listings_client_instance

    def _build_variation_plans(
        self,
        variation_families: List[List[str]],
        category_name: str,
        draft_builder,
        payload_builder,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        from src.models.amazon_listing import ListingVariation

        plans: List[Dict[str, Any]] = []
        logs: List[Dict[str, Any]] = []
        pre_submit_results: List[Dict[str, Any]] = []
        for family_skus in variation_families:
            family_data = [
                data for data in (
                    self.service.product_data_repo.get_full_product_data(sku)
                    for sku in family_skus
                )
                if data
            ]
            if not family_data:
                continue

            parent_sku = f"PARENT-{uuid.uuid4().hex[:12].upper()}"
            variation_result = self._get_variation_resolver().resolve_new_family(
                family_data,
                product_type=category_name,
            )
            if variation_result.decision == "blocked":
                for product_data in family_data:
                    pre_submit_results.append(
                        self._variation_block_result(
                            product_data["meow_sku"],
                            variation_result,
                        )
                    )
                continue
            variation_theme = variation_result.variation_theme
            child_attributes = variation_result.child_attributes

            parent_draft = draft_builder.build(family_data[0], product_type=category_name)
            parent_draft.sku = parent_sku
            parent_draft.offer.quantity = 0
            self._apply_approved_images(parent_draft)
            parent_draft.variation = ListingVariation(
                parentage_level="parent",
                variation_theme=variation_theme,
            )
            if parent_draft.content.title:
                parent_draft.content.title = (
                    self.service.variation_helper.generalize_parent_title(
                        parent_draft.content.title
                    )
                )
            parent_plan = payload_builder.build_plan(parent_draft)
            parent_coverage = self._evaluate_attribute_coverage(parent_plan)
            parent_blocked = parent_coverage.blocked
            if parent_blocked:
                pre_submit_results.append(
                    self._coverage_result(parent_sku, parent_plan, parent_coverage)
                )
            else:
                plans.append(parent_plan)

            for product_data in family_data:
                child_sku = product_data["meow_sku"]
                if parent_blocked:
                    pre_submit_results.append({
                        "sku": child_sku,
                        "status": "blocked_attribute_coverage",
                        "issues": 1,
                        "blocking_codes": ["PARENT_ATTRIBUTE_COVERAGE_BLOCKED"],
                        "warning_codes": [],
                        "missing_required": [],
                        "low_confidence_required": [],
                        "defaulted_required": [],
                        "covered_required": [],
                        "attribute_coverage_findings": [{
                            "code": "PARENT_ATTRIBUTE_COVERAGE_BLOCKED",
                            "attribute": "",
                            "attribute_names": [],
                            "severity": "ERROR",
                            "blocking": True,
                            "message": (
                                "Variation child skipped because parent listing "
                                "failed required attribute coverage"
                            ),
                        }],
                    })
                    continue
                commercial_result = self._evaluate_commercial_gate(
                    product_data=product_data,
                    product_type=category_name,
                )
                if commercial_result.blocked:
                    pre_submit_results.append(
                        self._commercial_block_result(child_sku, commercial_result)
                    )
                    continue
                product_data = self._with_commercial_publish_quantity(
                    product_data,
                    commercial_result,
                )
                child_draft = draft_builder.build(product_data, product_type=category_name)
                self._apply_approved_images(child_draft)
                child_draft.variation = ListingVariation(
                    parentage_level="child",
                    parent_sku=parent_sku,
                    variation_theme=variation_theme,
                    child_relationship_type="Variation",
                    theme_attributes=child_attributes.get(child_sku, {}),
                )
                child_plan = payload_builder.build_plan(child_draft)
                child_coverage = self._evaluate_attribute_coverage(child_plan)
                if child_coverage.blocked:
                    pre_submit_results.append(
                        self._coverage_result(child_sku, child_plan, child_coverage)
                    )
                    continue
                plans.append(child_plan)
                logs.append({
                    "meow_sku": child_sku,
                    "parent_sku": parent_sku,
                    "variation_attributes": child_attributes.get(child_sku, {}),
                    "listing_batch_id": None,
                    "status": "GENERATED",
                    "variation_theme": variation_theme,
                })

        return plans, logs, pre_submit_results

    def _resolve_existing_parent_append(
        self,
        product_data: Dict[str, Any],
        product_type: str,
    ):
        raw_data = product_data.get("raw_data") or {}
        associate_product_list = raw_data.get("associateProductList") or []
        if not associate_product_list:
            return None
        existing_meow_skus = (
            self.service.product_listing_repo.get_meow_skus_by_vendor_skus(
                associate_product_list
            )
        )
        family_log = self.service.listing_log_repo.find_log_for_family(
            list(existing_meow_skus.values())
        )
        if not family_log:
            return None
        parent_sku = family_log.get("parent_sku")
        existing_theme = family_log.get("variation_theme")
        if not parent_sku or parent_sku == "SINGLE_PRODUCT" or not existing_theme:
            return None
        existing_children = self.service.listing_log_repo.get_family_details_by_parent(
            parent_sku
        )
        result = self._get_variation_resolver().resolve_append_child(
            new_child_data=product_data,
            product_type=product_type,
            parent_sku=parent_sku,
            existing_theme=existing_theme,
            existing_children=existing_children,
        )
        if result.decision == "passed":
            self._get_variation_hierarchy_audit_coordinator().apply(
                result=result,
                parent_sku=parent_sku,
                existing_theme=existing_theme,
                existing_children=existing_children,
            )
        return result

    def _get_schema_service_or_none(self):
        if hasattr(self.service, "_schema_service_instance"):
            return self.service._schema_service_instance
        try:
            from src.services.amazon_schema_service import AmazonSchemaService

            self.service._schema_service_instance = AmazonSchemaService(self.service.db)
            return self.service._schema_service_instance
        except Exception as e:
            logger.warning("Amazon schema service unavailable: %s", e)
            self.service._schema_service_instance = None
            return None

    def _evaluate_attribute_coverage(self, plan: Dict[str, Any]):
        if hasattr(self.service, "_attribute_coverage_gate_instance"):
            gate = self.service._attribute_coverage_gate_instance
        else:
            from src.services.amazon_listing_attribute_coverage_gate import (
                AmazonListingAttributeCoverageGate,
            )

            gate = AmazonListingAttributeCoverageGate(
                schema_service=self._get_schema_service_or_none()
            )
            self.service._attribute_coverage_gate_instance = gate
        return gate.evaluate(plan)

    def _evaluate_commercial_gate(
        self,
        product_data: Dict[str, Any],
        product_type: str,
    ):
        gate = self._get_commercial_gate()
        return gate.evaluate(product_data=product_data, product_type=product_type)

    def _get_commercial_gate(self):
        if hasattr(self.service, "_commercial_gate_instance"):
            return self.service._commercial_gate_instance
        from src.repositories.amazon_listing_commercial_gate_repository import (
            AmazonListingCommercialGateRepository,
        )
        from src.services.amazon_listing_commercial_gate import (
            AmazonListingCommercialGate,
        )

        self.service._commercial_gate_instance = AmazonListingCommercialGate(
            audit_repo=AmazonListingCommercialGateRepository(self.service.db)
        )
        return self.service._commercial_gate_instance

    def _get_variation_resolver(self):
        if hasattr(self.service, "_variation_resolver_instance"):
            return self.service._variation_resolver_instance
        from src.services.amazon_variation_resolver import AmazonVariationResolver

        self.service._variation_resolver_instance = AmazonVariationResolver(
            audit_repo=self._get_variation_resolution_repo()
        )
        return self.service._variation_resolver_instance

    def _get_variation_resolution_repo(self):
        if hasattr(self.service, "_variation_resolution_repo_instance"):
            return self.service._variation_resolution_repo_instance
        from src.repositories.amazon_variation_resolution_repository import (
            AmazonVariationResolutionRepository,
        )

        self.service._variation_resolution_repo_instance = (
            AmazonVariationResolutionRepository(self.service.db)
        )
        return self.service._variation_resolution_repo_instance

    def _get_variation_hierarchy_audit_coordinator(self):
        if hasattr(self.service, "_variation_hierarchy_audit_coordinator_instance"):
            return self.service._variation_hierarchy_audit_coordinator_instance
        from src.services.variation_hierarchy_audit_coordinator import (
            VariationHierarchyAuditCoordinator,
        )

        self.service._variation_hierarchy_audit_coordinator_instance = (
            VariationHierarchyAuditCoordinator(self.service)
        )
        return self.service._variation_hierarchy_audit_coordinator_instance

    @staticmethod
    def _commercial_block_result(sku: str, result) -> Dict[str, Any]:
        return {
            "sku": sku,
            "status": "blocked_commercial_gate",
            "issues": len(result.blocking_codes),
            "blocking_codes": result.blocking_codes,
            "warning_codes": result.warning_codes,
            "audit_run_id": result.audit_run_id,
            "commercial_findings": [item.as_dict() for item in result.findings],
        }

    @staticmethod
    def _with_commercial_publish_quantity(
        product_data: Dict[str, Any],
        result,
    ) -> Dict[str, Any]:
        snapshot = getattr(result, "input_snapshot", None) or {}
        updated = dict(product_data)
        updated["source_publish_quantity"] = snapshot.get("source_publish_quantity")
        updated["publish_quantity"] = snapshot.get("publish_quantity")
        return updated

    @staticmethod
    def _variation_block_result(sku: str, result) -> Dict[str, Any]:
        return {
            "sku": sku,
            "status": "blocked_variation_resolution",
            "issues": len(result.blocking_codes),
            "blocking_codes": result.blocking_codes,
            "warning_codes": result.warning_codes,
            "audit_run_id": result.audit_run_id,
            "variation_findings": [item.as_dict() for item in result.findings],
        }

    @staticmethod
    def _attribute_coverage_block_result(sku: str, result) -> Dict[str, Any]:
        return {
            "sku": sku,
            "status": "blocked_attribute_coverage",
            "issues": len(result.findings),
            "blocking_codes": result.blocking_codes,
            "warning_codes": result.warning_codes,
            "missing_required": result.missing_required,
            "low_confidence_required": result.low_confidence_required,
            "defaulted_required": result.defaulted_required,
            "covered_required": result.covered_required,
            "attribute_coverage_findings": result.findings,
        }

    def _coverage_result(self, sku: str, plan: Dict[str, Any], result) -> Dict[str, Any]:
        return AttributeReviewPlanRouter(self.service).route(
            sku,
            plan,
            result,
            self._attribute_coverage_block_result,
        )

    def _apply_approved_images(self, draft) -> None:
        try:
            selector = self._get_image_selector()
            selected = selector.get_approved_images(draft.sku)
        except Exception as e:
            logger.warning("Image asset selection skipped for SKU=%s: %s", draft.sku, e)
            return
        if selected.main_image_url:
            draft.standard_product.images = [
                selected.main_image_url,
                *selected.other_image_urls,
            ]

    def _get_image_selector(self):
        if hasattr(self.service, "_image_selector_instance"):
            return self.service._image_selector_instance
        from src.repositories.amazon_listing_image_asset_repository import (
            AmazonListingImageAssetRepository,
        )
        from src.services.amazon_listing_image_selector import AmazonListingImageSelector

        self.service._image_selector_instance = AmazonListingImageSelector(
            AmazonListingImageAssetRepository(self.service.db)
        )
        return self.service._image_selector_instance
