"""Shadow audit adapter for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from src.repositories.amazon_api_submission_repository import (
    AmazonAPISubmissionRepository,
)
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
from src.services.requirement_models_v2 import PayloadBuildPlan


class ListingPayloadShadowAdapterV2:
    """Runs V2 beside V1 and persists a read-only shadow audit row."""

    OPERATION = "listing_payload_v2_shadow"

    def __init__(
        self,
        db: Session,
        engine: ListingPayloadEngineV2 | None = None,
        rule_loader: AttributeRuleLoader | None = None,
        submission_repo: AmazonAPISubmissionRepository | None = None,
    ):
        self.db = db
        self.engine = engine or ListingPayloadEngineV2(db)
        self.rule_loader = rule_loader or AttributeRuleLoader()
        self.submission_repo = submission_repo or AmazonAPISubmissionRepository(db)

    def run(
        self,
        product_type: str,
        sku: str,
        v1_plan: Dict[str, Any] | None = None,
        v1_status: str = "",
    ) -> Dict[str, Any]:
        """Build and persist a V2 shadow plan without changing V1 behavior."""
        normalized = str(product_type or "").strip().upper()
        try:
            rules = self.rule_loader.load(normalized)
            plan = self.engine.build_read_only_plan(normalized, sku, rules)
            response_body = self._success_response(plan)
            status = "shadow_built"
            submission_id = self.submission_repo.insert_submission(
                sku=sku,
                operation=self.OPERATION,
                status=status,
                product_type=normalized,
                request_payload=self._request_payload(
                    normalized,
                    sku,
                    v1_plan,
                    v1_status,
                ),
                response_body=response_body,
            )
            return {
                "sku": sku,
                "status": status,
                "submission_id": submission_id,
                "v2_blocking": bool(response_body["summary"]["blocking_codes"]),
                "v2_findings": response_body["summary"]["finding_count"],
            }
        except Exception as exc:
            status = "shadow_failed"
            submission_id = self.submission_repo.insert_submission(
                sku=sku,
                operation=self.OPERATION,
                status=status,
                product_type=normalized,
                request_payload=self._request_payload(
                    normalized,
                    sku,
                    v1_plan,
                    v1_status,
                ),
                response_body={"engine": "v2", "shadow": True},
                error_message=str(exc),
            )
            return {
                "sku": sku,
                "status": status,
                "submission_id": submission_id,
                "error_message": str(exc),
            }

    def _request_payload(
        self,
        product_type: str,
        sku: str,
        v1_plan: Dict[str, Any] | None,
        v1_status: str,
    ) -> Dict[str, Any]:
        attributes = self._v1_attributes(v1_plan)
        return {
            "engine": "shadow",
            "sku": sku,
            "product_type": product_type,
            "v1_status": v1_status,
            "v1_attribute_names": sorted(attributes),
            "v1_attributes": attributes,
        }

    @staticmethod
    def _success_response(plan: PayloadBuildPlan) -> Dict[str, Any]:
        finding_codes = [str(item.get("code") or "") for item in plan.findings]
        return {
            "engine": "v2",
            "shadow": True,
            "summary": {
                "covered_required_count": len(plan.covered_required_paths),
                "missing_required_paths": list(plan.missing_required_paths),
                "low_confidence_required_paths": list(
                    plan.low_confidence_required_paths
                ),
                "pending_review_paths": list(plan.pending_review_paths),
                "safe_default_paths": list(plan.safe_default_paths),
                "finding_count": len(plan.findings),
                "blocking_codes": sorted({code for code in finding_codes if code}),
                "condition_trace_count": len(plan.requirement_tree.condition_traces),
                "required_path_count": len(plan.requirement_tree.required_paths),
            },
            "v2_attribute_names": sorted(plan.attributes),
            "v2_attributes": plan.attributes,
            "v2_findings": list(plan.findings),
            "v2_required_paths": list(plan.requirement_tree.required_paths),
            "v2_condition_traces": [
                trace.as_dict() for trace in plan.requirement_tree.condition_traces
            ],
            "v2_pending_review_paths": list(plan.pending_review_paths),
        }

    @staticmethod
    def _v1_attributes(v1_plan: Dict[str, Any] | None) -> Dict[str, Any]:
        if not isinstance(v1_plan, dict):
            return {}
        attributes = v1_plan.get("attributes")
        return dict(attributes or {}) if isinstance(attributes, dict) else {}
