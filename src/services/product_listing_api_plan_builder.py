"""Build API-native Amazon listing payload plans."""

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from src.services.product_listing_scope import (
    ListingScope,
    ProductListingScopeFilter,
)
from src.services.attribute_review_plan_router import AttributeReviewPlanRouter

logger = logging.getLogger(__name__)


@dataclass
class _CoverageResultAdapterV2:
    """V1-shaped coverage result backed by a V2 PayloadBuildPlan."""

    payload_build_plan: Any
    blocked: bool
    review_required: List[str]
    blocking_codes: List[str]
    warning_codes: List[str]
    findings: List[Dict[str, Any]]
    missing_required: List[str]
    low_confidence_required: List[str]
    defaulted_required: List[str]
    covered_required: List[str]
    engine: str = "v2"


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
                self._record_v2_shadow_result(
                    product_type=category_name,
                    sku=sku,
                    v1_status="blocked_commercial_gate",
                )
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
                plan, coverage_result = self._build_listing_plan(draft, payload_builder)
                status = (
                    "blocked_attribute_coverage"
                    if coverage_result.blocked
                    else "plan_generated"
                )
                self._record_v2_shadow_result(
                    product_type=category_name,
                    sku=sku,
                    v1_plan=plan,
                    v1_status=status,
                )
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
            plan, coverage_result = self._build_listing_plan(draft, payload_builder)
            status = (
                "blocked_attribute_coverage"
                if coverage_result.blocked
                else "plan_generated"
            )
            self._record_v2_shadow_result(
                product_type=category_name,
                sku=sku,
                v1_plan=plan,
                v1_status=status,
            )
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

    def build_v2_payload_plan_for_sku(self, product_type: str, sku: str):
        """Build an authoritative V2 PayloadBuildPlan for one SKU without submitting."""
        from src.models.amazon_listing import ListingVariation
        from src.services.amazon_listing_draft_builder import AmazonListingDraftBuilder
        from src.services.amazon_listing_payload_builder import AmazonListingPayloadBuilder

        normalized = str(product_type or "").strip().upper()
        product_data = self.service.product_data_repo.get_full_product_data(sku)
        if not product_data:
            raise ValueError(f"SKU not found: {sku}")

        commercial_result = self._evaluate_commercial_gate(
            product_data=product_data,
            product_type=normalized,
        )
        if commercial_result.blocked:
            raise ValueError(f"commercial_gate_blocked:{sku}")

        product_data = self._with_commercial_publish_quantity(
            product_data,
            commercial_result,
        )
        draft_builder = AmazonListingDraftBuilder()
        payload_builder = AmazonListingPayloadBuilder(
            schema_service=self._get_schema_service_or_none()
        )
        draft = draft_builder.build(product_data, product_type=normalized)
        self._apply_approved_images(draft)

        append_result = self._resolve_existing_parent_append(
            product_data=product_data,
            product_type=normalized,
        )
        if append_result is not None and append_result.decision != "blocked":
            draft.variation = ListingVariation(
                parentage_level="child",
                parent_sku=append_result.parent_sku,
                variation_theme=append_result.variation_theme,
                child_relationship_type="Variation",
                theme_attributes=append_result.child_attributes.get(sku, {}),
            )

        previous_mode = getattr(self.service, "listing_payload_engine_mode", "v1")
        self.service.listing_payload_engine_mode = "v2"
        try:
            _plan, coverage_result = self._build_listing_plan(draft, payload_builder)
        finally:
            self.service.listing_payload_engine_mode = previous_mode

        if getattr(coverage_result, "engine", "") != "v2":
            raise ValueError(f"v2_plan_not_built:{sku}")
        return coverage_result.payload_build_plan

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
                    self._record_v2_shadow_result(
                        product_type=category_name,
                        sku=product_data["meow_sku"],
                        v1_status="blocked_variation_resolution",
                    )
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
            parent_plan, parent_coverage = self._build_listing_plan(
                parent_draft,
                payload_builder,
            )
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
                    self._record_v2_shadow_result(
                        product_type=category_name,
                        sku=child_sku,
                        v1_status="blocked_commercial_gate",
                    )
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
                child_plan, child_coverage = self._build_listing_plan(
                    child_draft,
                    payload_builder,
                )
                status = (
                    "blocked_attribute_coverage"
                    if child_coverage.blocked
                    else "plan_generated"
                )
                self._record_v2_shadow_result(
                    product_type=category_name,
                    sku=child_sku,
                    v1_plan=child_plan,
                    v1_status=status,
                )
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

    def _build_listing_plan(self, draft, payload_builder) -> tuple[Dict[str, Any], Any]:
        if self._listing_payload_engine_mode() == "v2":
            return self._build_v2_listing_plan(draft)
        plan = payload_builder.build_plan(draft)
        return plan, self._evaluate_attribute_coverage(plan)

    def _build_v2_listing_plan(self, draft) -> tuple[Dict[str, Any], _CoverageResultAdapterV2]:
        from src.services.attribute_rule_loader import AttributeRuleLoader

        rules = AttributeRuleLoader().load(draft.product_type)
        overrides = self._get_review_adapter_v2().build_overrides_from_decisions(
            category=draft.product_type,
            sku=draft.sku,
        )
        payload_build_plan = self._get_listing_payload_engine_v2().build_read_only_plan_from_draft(
            draft=draft,
            rules=rules,
            overrides=overrides or None,
        )
        plan = {
            "sku": payload_build_plan.sku,
            "product_type": payload_build_plan.product_type,
            "attributes": payload_build_plan.attributes,
            "listing_payload_engine": "v2",
            "v2_plan_summary": {
                "covered_required_paths": list(payload_build_plan.covered_required_paths),
                "missing_required_paths": list(payload_build_plan.missing_required_paths),
                "low_confidence_required_paths": list(
                    payload_build_plan.low_confidence_required_paths
                ),
                "pending_review_paths": list(payload_build_plan.pending_review_paths),
                "safe_default_paths": list(payload_build_plan.safe_default_paths),
                "findings": list(payload_build_plan.findings),
            },
        }
        coverage = _CoverageResultAdapterV2(
            payload_build_plan=payload_build_plan,
            blocked=bool(payload_build_plan.findings),
            review_required=list(payload_build_plan.pending_review_paths),
            blocking_codes=sorted(
                {
                    str(item.get("code") or "")
                    for item in payload_build_plan.findings
                    if str(item.get("code") or "").strip()
                }
            ),
            warning_codes=[],
            findings=list(payload_build_plan.findings),
            missing_required=list(payload_build_plan.missing_required_paths),
            low_confidence_required=list(payload_build_plan.low_confidence_required_paths),
            defaulted_required=list(payload_build_plan.safe_default_paths),
            covered_required=list(payload_build_plan.covered_required_paths),
        )
        return plan, coverage

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
        if getattr(result, "engine", "") == "v2":
            return self._coverage_result_v2(sku, plan, result)
        return AttributeReviewPlanRouter(self.service).route(
            sku,
            plan,
            result,
            self._attribute_coverage_block_result,
        )

    def _coverage_result_v2(
        self,
        sku: str,
        plan: Dict[str, Any],
        result: _CoverageResultAdapterV2,
    ) -> Dict[str, Any]:
        if self._is_v2_review_only_block(result):
            review_count = self._get_review_adapter_v2().persist_pending_paths(
                category=result.payload_build_plan.product_type,
                sku=sku,
                parent_sku=self._parent_sku_from_plan(plan),
                path_key_version=(
                    result.payload_build_plan.requirement_tree.path_key_version
                ),
                plan_snapshot=result.payload_build_plan.as_dict(),
                resolution_root=result.payload_build_plan.resolution_tree,
            )
            return {
                "sku": sku,
                "status": "needs_review",
                "issues": len(result.findings),
                "review_id": review_count,
                "review_required": result.review_required,
                "blocking_codes": result.blocking_codes,
                "warning_codes": result.warning_codes,
                "attribute_coverage_findings": result.findings,
            }
        return self._attribute_coverage_block_result(sku, result)

    @staticmethod
    def _is_v2_review_only_block(result: _CoverageResultAdapterV2) -> bool:
        return bool(result.review_required) and set(result.blocking_codes or []) == {
            "NEEDS_REVIEW_REQUIRED_ATTRIBUTE"
        }

    @staticmethod
    def _parent_sku_from_plan(plan: Dict[str, Any]) -> str | None:
        relationships = (
            (plan.get("attributes") or {}).get("child_parent_sku_relationship") or []
        )
        for item in relationships:
            if isinstance(item, dict) and item.get("parent_sku"):
                return str(item["parent_sku"])
        return None

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

    def _record_v2_shadow_result(
        self,
        product_type: str,
        sku: str,
        v1_plan: Dict[str, Any] | None = None,
        v1_status: str = "",
    ) -> Dict[str, Any] | None:
        if self._listing_payload_engine_mode() != "shadow":
            return None
        try:
            result = self._get_listing_payload_shadow_adapter_v2().run(
                product_type=product_type,
                sku=sku,
                v1_plan=v1_plan,
                v1_status=v1_status,
            )
            logger.info(
                "V2 shadow audit SKU=%s status=%s submission_id=%s",
                sku,
                result.get("status"),
                result.get("submission_id"),
            )
            return result
        except Exception as exc:
            logger.warning("V2 shadow audit skipped SKU=%s: %s", sku, exc)
            return {
                "sku": sku,
                "status": "shadow_adapter_failed",
                "error_message": str(exc),
            }

    def _listing_payload_engine_mode(self) -> str:
        configured = getattr(self.service, "listing_payload_engine_mode", None)
        if configured is None:
            configured = os.getenv("LISTING_PAYLOAD_ENGINE", "v1")
        return str(configured or "v1").strip().lower()

    def _get_listing_payload_shadow_adapter_v2(self):
        if hasattr(self.service, "_listing_payload_shadow_adapter_v2_instance"):
            return self.service._listing_payload_shadow_adapter_v2_instance
        from src.services.listing_payload_shadow_adapter_v2 import (
            ListingPayloadShadowAdapterV2,
        )

        self.service._listing_payload_shadow_adapter_v2_instance = (
            ListingPayloadShadowAdapterV2(self.service.db)
        )
        return self.service._listing_payload_shadow_adapter_v2_instance

    def _get_listing_payload_engine_v2(self):
        if hasattr(self.service, "_listing_payload_engine_v2_instance"):
            return self.service._listing_payload_engine_v2_instance
        from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2

        self.service._listing_payload_engine_v2_instance = ListingPayloadEngineV2(
            self.service.db,
            schema_service=self._get_schema_service_or_none(),
        )
        return self.service._listing_payload_engine_v2_instance

    def _get_review_adapter_v2(self):
        if hasattr(self.service, "_review_adapter_v2_instance"):
            return self.service._review_adapter_v2_instance
        from src.services.review_adapter_v2 import ReviewAdapterV2

        self.service._review_adapter_v2_instance = ReviewAdapterV2(db=self.service.db)
        return self.service._review_adapter_v2_instance
