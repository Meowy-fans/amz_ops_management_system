"""Amazon Listing Submitter — submits new listing plans via putListingsItem."""
import json
import logging
from typing import Any, Dict, List, Optional

from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class AmazonListingSubmitter:
    """Submits listing plans (sku + product_type + attributes) to Amazon SP-API.

    Supports dry-run mode (build payloads, log, record in DB) and real
    submission mode (call putListingsItem or VALIDATION_PREVIEW).
    """

    def __init__(
        self,
        db,
        reporter: Optional[ProgressReporter] = None,
        listings_client: Any = None,
        submission_repo: Any = None,
        schema_service: Any = None,
        quality_gate: Any = None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self._submission_repo_instance = submission_repo
        self._schema_service_instance = schema_service
        self._quality_gate_instance = quality_gate

    def submit(
        self,
        plans: List[Dict[str, Any]],
        dry_run: bool = True,
        validation_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Submit listing plans one by one.

        Args:
            plans: List of {"sku", "product_type", "attributes"} dicts.
            dry_run: If True, log payloads without calling the API.
            validation_only: If True, use VALIDATION_PREVIEW mode for real calls.

        Returns:
            List of result dicts with sku, status, request_id, issues.
        """
        if not plans:
            self.reporter.emit("No listing plans to submit.")
            return []

        quality_results = self._get_quality_gate().prepare_plans(plans)
        submittable_plans = [
            item["plan"] for item in quality_results if not item["blocked"]
        ]

        # Pre-validation: local schema check (best-effort, Amazon is authoritative)
        self._pre_validate(submittable_plans)

        listings_client = None if dry_run else self._get_listings_client()
        submission_repo = self._get_submission_repo()

        results: List[Dict[str, Any]] = []
        for quality_result in quality_results:
            plan = quality_result["plan"]
            sku = plan["sku"]
            product_type = plan["product_type"]
            attributes = plan["attributes"]
            quality_findings = quality_result["findings"]

            if quality_result["blocked"]:
                submission_repo.insert_submission(
                    sku=sku,
                    operation="create",
                    status="blocked_quality_gate",
                    product_type=product_type,
                    request_payload={
                        "productType": product_type,
                        "attributes": attributes,
                        "qualityFindings": quality_findings,
                    },
                )
                self.reporter.emit(
                    f"  BLOCK {sku}: quality gate findings={len(quality_findings)}"
                )
                results.append(
                    {
                        "sku": sku,
                        "status": "blocked",
                        "issues": len(quality_findings),
                        "quality_findings": quality_findings,
                    }
                )
                continue

            if dry_run:
                self.reporter.emit(f"\n--- DRY RUN: {sku} ({product_type}) ---")
                for finding in quality_findings:
                    self.reporter.emit(
                        f"  QUALITY {finding['severity']} {finding['code']}: "
                        f"{finding['message']}"
                    )
                self.reporter.emit(
                    json.dumps(attributes, indent=2, ensure_ascii=False)[:2000]
                )
                submission_repo.insert_submission(
                    sku=sku,
                    operation="create",
                    status="dry_run",
                    product_type=product_type,
                    request_payload={
                        "productType": product_type,
                        "attributes": attributes,
                        "qualityFindings": quality_findings,
                    },
                )
                results.append(
                    {
                        "sku": sku,
                        "status": "dry_run",
                        "quality_findings": quality_findings,
                    }
                )
            else:
                try:
                    if validation_only:
                        response = listings_client.validation_preview(
                            sku=sku,
                            product_type=product_type,
                            attributes=attributes,
                        )
                    else:
                        response = listings_client.put_listings_item(
                            sku=sku,
                            product_type=product_type,
                            attributes=attributes,
                        )
                    body = response["body"]
                    request_id = response["headers"].get("x-amzn-RequestId", "")
                    issues = body.get("issues", [])
                    status = body.get("status", "ACCEPTED")
                    submission_repo.insert_submission(
                        sku=sku,
                        operation="create",
                        status="success" if not issues else "issues_found",
                        amazon_request_id=request_id,
                        product_type=product_type,
                        request_payload={
                            "productType": product_type,
                            "attributes": attributes,
                            "qualityFindings": quality_findings,
                        },
                        response_body=body,
                    )
                    issue_count = len(issues)
                    self.reporter.emit(
                        f"  {status} {sku} request_id={request_id} issues={issue_count}"
                    )
                    results.append(
                        {
                            "sku": sku,
                            "status": status,
                            "request_id": request_id,
                            "issues": issue_count,
                            "quality_findings": quality_findings,
                        }
                    )
                except Exception as e:
                    logger.error("Submission failed for SKU=%s: %s", sku, e)
                    submission_repo.insert_submission(
                        sku=sku,
                        operation="create",
                        status="failed",
                        product_type=product_type,
                        request_payload={
                            "productType": product_type,
                            "attributes": attributes,
                            "qualityFindings": quality_findings,
                        },
                        error_message=str(e),
                    )
                    self.reporter.emit(f"  FAIL {sku}: {e}")
                    results.append(
                        {"sku": sku, "status": "failed", "error": str(e)}
                    )

        success = sum(1 for r in results if r["status"] in ("success", "ACCEPTED", "dry_run"))
        fail = sum(1 for r in results if r["status"] == "failed")
        issues = sum(1 for r in results if r["status"] == "issues_found")
        self.reporter.emit(
            f"\nSubmission Complete: {len(results)} SKUs "
            f"(ok={success} fail={fail} with_issues={issues})"
        )
        return results

    # ── lazy init ─────────────────────────────────────────────────

    def _get_listings_client(self):
        if self._listings_client_instance is not None:
            return self._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self._listings_client_instance = AmazonListingsClient()
        return self._listings_client_instance

    def _get_submission_repo(self):
        if self._submission_repo_instance is not None:
            return self._submission_repo_instance
        from src.repositories.amazon_api_submission_repository import (
            AmazonAPISubmissionRepository,
        )

        self._submission_repo_instance = AmazonAPISubmissionRepository(self.db)
        return self._submission_repo_instance

    def _get_schema_service(self):
        if self._schema_service_instance is not None:
            return self._schema_service_instance
        from src.services.amazon_schema_service import AmazonSchemaService

        self._schema_service_instance = AmazonSchemaService(self.db)
        return self._schema_service_instance

    def _get_quality_gate(self):
        if self._quality_gate_instance is not None:
            return self._quality_gate_instance
        from src.services.amazon_listing_quality_gate import AmazonListingQualityGate

        self._quality_gate_instance = AmazonListingQualityGate(
            schema_service=self._get_schema_service()
        )
        return self._quality_gate_instance

    # ── pre-validation ────────────────────────────────────────────

    def _pre_validate(self, plans: List[Dict[str, Any]]) -> None:
        """Run local schema validation against cached Product Type Definitions.

        Logs warnings for missing required fields. Does not block submission.
        """
        try:
            svc = self._get_schema_service()
        except Exception:
            return  # schema service unavailable, skip pre-check

        for plan in plans:
            pt = plan.get("product_type", "")
            attrs = plan.get("attributes", {})
            if not pt or not attrs:
                continue
            try:
                missing = svc.validate_attributes(pt, attrs)
                if missing:
                    names = [m["property"] for m in missing]
                    self.reporter.emit(
                        f"  PRE-CHECK {plan['sku']}: missing {names}"
                    )
            except Exception:
                # Schema not cached for this product type; skip
                pass
