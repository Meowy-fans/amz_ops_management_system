"""Amazon Listing Submitter — submits new listing plans via putListingsItem."""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from infrastructure.amazon.api_client import AmazonAPIException
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
        rule_loader: Any = None,
        confirmation_delay_seconds: float = 0,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self._submission_repo_instance = submission_repo
        self._schema_service_instance = schema_service
        self._quality_gate_instance = quality_gate
        self._rule_loader_instance = rule_loader
        self.confirmation_delay_seconds = confirmation_delay_seconds

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
        if not dry_run:
            quality_results = [
                self._apply_live_blocking_findings(item)
                for item in quality_results
            ]
        submittable_plans = [
            item["plan"] for item in quality_results if not item["blocked"]
        ]

        # Pre-validation: local schema check (best-effort, Amazon is authoritative)
        self._pre_validate(submittable_plans)

        strict_dry_run = dry_run and validation_only
        listings_client = (
            self._get_listings_client() if (not dry_run or strict_dry_run) else None
        )
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

            if dry_run and not validation_only:
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
            elif dry_run and validation_only:
                result = self._run_validation_preview(
                    listings_client=listings_client,
                    submission_repo=submission_repo,
                    sku=sku,
                    product_type=product_type,
                    attributes=attributes,
                    quality_findings=quality_findings,
                )
                results.append(result)
            else:
                rule_block = self._rule_mode_block_result(
                    sku=sku,
                    product_type=product_type,
                    attributes=attributes,
                    quality_findings=quality_findings,
                    submission_repo=submission_repo,
                )
                if rule_block is not None:
                    results.append(rule_block)
                    continue

                try:
                    existing_listing = self._get_existing_listing(
                        listings_client=listings_client,
                        sku=sku,
                    )
                except Exception as e:
                    logger.error("Existing listing check failed for SKU=%s: %s", sku, e)
                    submission_repo.insert_submission(
                        sku=sku,
                        operation="create",
                        status="failed_existing_check",
                        product_type=product_type,
                        request_payload={
                            "productType": product_type,
                            "attributes": attributes,
                            "qualityFindings": quality_findings,
                        },
                        error_message=str(e),
                    )
                    self.reporter.emit(
                        f"  FAIL {sku}: existing listing check failed: {e}"
                    )
                    results.append({"sku": sku, "status": "failed", "error": str(e)})
                    continue

                if existing_listing is not None:
                    submission_repo.insert_submission(
                        sku=sku,
                        operation="create",
                        status="skipped_existing",
                        product_type=product_type,
                        request_payload={
                            "productType": product_type,
                            "attributes": attributes,
                            "qualityFindings": quality_findings,
                        },
                        response_body=existing_listing,
                    )
                    self.reporter.emit(
                        f"  SKIP {sku}: listing already exists on Amazon"
                    )
                    results.append(
                        {
                            "sku": sku,
                            "status": "skipped_existing",
                            "issues": 0,
                            "quality_findings": quality_findings,
                        }
                    )
                    continue

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
                    if issues:
                        submission_status = "issues_found"
                    elif status != "ACCEPTED":
                        submission_status = "not_accepted"
                    else:
                        submission_status = "success"
                    response_body = body
                    result_status = status
                    result_issue_count = len(issues)
                    confirmation_error = None
                    if (
                        not validation_only
                        and status == "ACCEPTED"
                        and not issues
                    ):
                        confirmation = self._confirm_submitted_listing(
                            listings_client=listings_client,
                            sku=sku,
                        )
                        submission_status = confirmation["status"]
                        response_body = {
                            "put_response": body,
                            "confirm_response": confirmation.get("body"),
                        }
                        result_status = confirmation["status"]
                        result_issue_count = confirmation.get("issues", 0)
                        confirmation_error = confirmation.get("error")

                    submission_repo.insert_submission(
                        sku=sku,
                        operation="create",
                        status=submission_status,
                        amazon_request_id=request_id,
                        product_type=product_type,
                        request_payload={
                            "productType": product_type,
                            "attributes": attributes,
                            "qualityFindings": quality_findings,
                        },
                        response_body=response_body,
                        error_message=confirmation_error,
                    )
                    issue_count = result_issue_count
                    self.reporter.emit(
                        f"  {result_status} {sku} request_id={request_id} issues={issue_count}"
                    )
                    results.append(
                        {
                            "sku": sku,
                            "status": result_status,
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

        success = sum(
            1 for r in results
            if r["status"] in (
                "ACCEPTED",
                "dry_run",
                "listing_confirmed",
                "validation_preview_passed",
            )
        )
        fail = sum(1 for r in results if r["status"] == "failed")
        issues = sum(
            1 for r in results
            if r["status"] in ("issues_found", "confirmed_with_issues")
        )
        self.reporter.emit(
            f"\nSubmission Complete: {len(results)} SKUs "
            f"(ok={success} fail={fail} with_issues={issues})"
        )
        return results

    @staticmethod
    def _apply_live_blocking_findings(quality_result: Dict[str, Any]) -> Dict[str, Any]:
        """Promote configured nonblocking dry-run findings to LIVE blockers."""
        if quality_result.get("blocked"):
            return quality_result
        findings = quality_result.get("findings") or []
        if not any(bool(item.get("live_blocking")) for item in findings):
            return quality_result
        promoted = dict(quality_result)
        promoted["blocked"] = True
        return promoted

    def _run_validation_preview(
        self,
        listings_client: Any,
        submission_repo: Any,
        sku: str,
        product_type: str,
        attributes: Dict[str, Any],
        quality_findings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Run strict dry-run read checks and VALIDATION_PREVIEW without PUT."""
        try:
            existing_listing = self._get_existing_listing(
                listings_client=listings_client,
                sku=sku,
            )
        except Exception as e:
            logger.error("Existing listing check failed for SKU=%s: %s", sku, e)
            submission_repo.insert_submission(
                sku=sku,
                operation="create",
                status="failed_existing_check",
                product_type=product_type,
                request_payload={
                    "productType": product_type,
                    "attributes": attributes,
                    "qualityFindings": quality_findings,
                    "strictDryRun": True,
                },
                error_message=str(e),
            )
            self.reporter.emit(f"  FAIL {sku}: existing listing check failed: {e}")
            return {"sku": sku, "status": "failed", "error": str(e)}

        request_payload = {
            "productType": product_type,
            "attributes": attributes,
            "qualityFindings": quality_findings,
            "strictDryRun": True,
        }
        if existing_listing is not None:
            submission_repo.insert_submission(
                sku=sku,
                operation="create",
                status="skipped_existing",
                product_type=product_type,
                request_payload=request_payload,
                response_body=existing_listing,
            )
            self.reporter.emit(f"  SKIP {sku}: listing already exists on Amazon")
            return {
                "sku": sku,
                "status": "skipped_existing",
                "issues": 0,
                "quality_findings": quality_findings,
            }

        try:
            response = listings_client.validation_preview(
                sku=sku,
                product_type=product_type,
                attributes=attributes,
            )
            body = response["body"]
            request_id = response["headers"].get("x-amzn-RequestId", "")
            issues = body.get("issues", [])
            status = (
                "validation_preview_issues"
                if issues
                else "validation_preview_passed"
            )
            submission_repo.insert_submission(
                sku=sku,
                operation="create",
                status=status,
                amazon_request_id=request_id,
                product_type=product_type,
                request_payload=request_payload,
                response_body=body,
            )
            self.reporter.emit(
                f"  {status} {sku} request_id={request_id} issues={len(issues)}"
            )
            return {
                "sku": sku,
                "status": status,
                "request_id": request_id,
                "issues": len(issues),
                "quality_findings": quality_findings,
            }
        except Exception as e:
            logger.error("Validation preview failed for SKU=%s: %s", sku, e)
            submission_repo.insert_submission(
                sku=sku,
                operation="create",
                status="validation_preview_failed",
                product_type=product_type,
                request_payload=request_payload,
                error_message=str(e),
            )
            self.reporter.emit(f"  FAIL {sku}: validation preview failed: {e}")
            return {"sku": sku, "status": "failed", "error": str(e)}

    def _rule_mode_block_result(
        self,
        sku: str,
        product_type: str,
        attributes: Dict[str, Any],
        quality_findings: List[Dict[str, Any]],
        submission_repo: Any,
    ) -> Optional[Dict[str, Any]]:
        """Block LIVE submits unless attribute rules explicitly allow them."""
        rule_loader = self._get_rule_loader()
        mode = rule_loader.mode(product_type)
        if mode == getattr(rule_loader, "LIVE_ELIGIBLE_MODE", "live_eligible"):
            return None

        finding = {
            "severity": "ERROR",
            "code": "RULE_MODE_NOT_LIVE_ELIGIBLE",
            "message": (
                f"Product type {product_type} attribute rules are mode={mode}; "
                "LIVE submit requires mode=live_eligible"
            ),
            "attribute_names": [],
            "blocking": True,
        }
        submission_repo.insert_submission(
            sku=sku,
            operation="create",
            status="blocked_by_rule_mode",
            product_type=product_type,
            request_payload={
                "productType": product_type,
                "attributes": attributes,
                "qualityFindings": quality_findings,
                "ruleMode": mode,
            },
            error_message=finding["message"],
        )
        self.reporter.emit(f"  BLOCK {sku}: rule mode {mode} is not LIVE eligible")
        return {
            "sku": sku,
            "status": "blocked_by_rule_mode",
            "issues": 1,
            "quality_findings": quality_findings,
            "rule_mode": mode,
            "blocking_codes": [finding["code"]],
        }

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

    def _get_rule_loader(self):
        if self._rule_loader_instance is not None:
            return self._rule_loader_instance
        from src.services.attribute_rule_loader import AttributeRuleLoader

        self._rule_loader_instance = AttributeRuleLoader()
        return self._rule_loader_instance

    # ── pre-validation ────────────────────────────────────────────

    def _get_existing_listing(
        self,
        listings_client: Any,
        sku: str,
    ) -> Optional[Dict[str, Any]]:
        """Return Amazon listing body when SKU exists; return None on 404.

        Any non-404 error is raised so create submissions fail closed instead
        of risking a full replacement with putListingsItem.
        """
        try:
            response = listings_client.get_listings_item(
                sku=sku,
                included_data=["summaries", "issues", "attributes", "productTypes"],
            )
            return response.get("body", {})
        except AmazonAPIException as exc:
            if exc.status_code == 404:
                return None
            raise

    def _confirm_submitted_listing(
        self,
        listings_client: Any,
        sku: str,
    ) -> Dict[str, Any]:
        """Confirm a submitted listing without rewriting the PUT outcome."""
        if self.confirmation_delay_seconds > 0:
            time.sleep(self.confirmation_delay_seconds)
        try:
            body = self._get_existing_listing(listings_client=listings_client, sku=sku)
        except Exception as exc:
            return {
                "status": "confirmation_failed",
                "issues": 0,
                "body": None,
                "error": str(exc),
            }
        if body is None:
            return {
                "status": "accepted_pending_confirmation",
                "issues": 0,
                "body": None,
            }
        issues = body.get("issues", []) if isinstance(body, dict) else []
        if issues:
            return {
                "status": "confirmed_with_issues",
                "issues": len(issues),
                "body": body,
            }
        return {
            "status": "listing_confirmed",
            "issues": 0,
            "body": body,
        }

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
