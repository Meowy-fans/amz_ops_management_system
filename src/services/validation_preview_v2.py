"""V2 Amazon VALIDATION_PREVIEW integration without PUT."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.services.requirement_models_v2 import PayloadBuildPlan


@dataclass
class ValidationPreviewResult:
    """Result of one Amazon VALIDATION_PREVIEW call for a V2 plan."""

    sku: str
    product_type: str
    status: str
    amazon_request_id: Optional[str] = None
    issues: List[Dict[str, Any]] = field(default_factory=list)
    submission_id: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class ValidationPreviewComparison:
    """Diff between Amazon VALIDATION_PREVIEW issues and V2 coverage findings."""

    sku: str
    amazon_issue_count: int
    v2_finding_count: int
    matched: List[Dict[str, Any]] = field(default_factory=list)
    amazon_only: List[Dict[str, Any]] = field(default_factory=list)
    v2_only: List[Dict[str, Any]] = field(default_factory=list)


class ValidationPreviewV2:
    """Run Amazon VALIDATION_PREVIEW for V2 PayloadBuildPlans without PUT."""

    EXPLAINABLE_AMAZON_ONLY_CODES = frozenset(
        {
            "18448",  # recommended attribute / business warning class
            "90000900",  # dimension / range warnings observed on CABINET canary
        }
    )

    def __init__(
        self,
        db: Any = None,
        listings_client: Any = None,
        submission_repo: Any = None,
        marketplace_id: str = "ATVPDKIKX0DER",
    ):
        self.db = db
        self._listings_client = listings_client
        self._submission_repo = submission_repo
        self.marketplace_id = marketplace_id

    def preview(self, plan: PayloadBuildPlan) -> ValidationPreviewResult:
        """Call Amazon VALIDATION_PREVIEW for one V2 plan and persist audit row."""
        attributes = plan.attributes or {}
        try:
            response = self._get_listings_client().validation_preview(
                plan.sku,
                plan.product_type,
                attributes,
            )
        except Exception as exc:
            return self._persist_failure(plan, attributes, exc)

        return self._persist_response(plan, attributes, response)

    def compare(
        self,
        plan: PayloadBuildPlan,
        result: ValidationPreviewResult,
    ) -> ValidationPreviewComparison:
        """Match Amazon issues to V2 coverage findings by attribute root."""
        v2_findings = list(plan.findings or [])
        amazon_issues = list(result.issues or [])

        v2_roots = {
            self._root_of(finding.get("path_key") or ""): finding
            for finding in v2_findings
            if finding.get("path_key")
        }
        matched: List[Dict[str, Any]] = []
        amazon_only: List[Dict[str, Any]] = []
        matched_roots: set[str] = set()

        for issue in amazon_issues:
            attr_names = issue.get("attributeNames") or []
            root = self._root_of(attr_names[0]) if attr_names else ""
            if root and root in v2_roots:
                matched.append({
                    "attribute": root,
                    "amazon_issue": issue,
                    "v2_finding": v2_roots[root],
                })
                matched_roots.add(root)
            else:
                amazon_only.append(issue)

        v2_only = [
            finding
            for root, finding in v2_roots.items()
            if root not in matched_roots
        ]

        return ValidationPreviewComparison(
            sku=plan.sku,
            amazon_issue_count=len(amazon_issues),
            v2_finding_count=len(v2_findings),
            matched=matched,
            amazon_only=amazon_only,
            v2_only=v2_only,
        )

    @classmethod
    def unexplained_amazon_only(
        cls,
        comparison: ValidationPreviewComparison,
        allowed_codes: frozenset[str] | set[str] | None = None,
        ignored_attribute_roots: frozenset[str] | set[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """Return Amazon-only issues that are not warnings or allowlisted codes."""
        allowed = set(allowed_codes or cls.EXPLAINABLE_AMAZON_ONLY_CODES)
        ignored = {
            cls._root_of(str(name or ""))
            for name in (ignored_attribute_roots or [])
            if str(name or "").strip()
        }
        unexplained: List[Dict[str, Any]] = []
        for issue in comparison.amazon_only:
            severity = str(issue.get("severity") or "ERROR").upper()
            code = str(issue.get("code") or "").strip()
            attr_names = issue.get("attributeNames") or []
            root = cls._root_of(attr_names[0]) if attr_names else ""
            if severity == "WARNING":
                continue
            if code in allowed:
                continue
            if root in ignored:
                continue
            unexplained.append(issue)
        return unexplained

    @classmethod
    def comparison_is_clean(
        cls,
        comparison: ValidationPreviewComparison,
        allowed_codes: frozenset[str] | set[str] | None = None,
        ignored_attribute_roots: frozenset[str] | set[str] | None = None,
    ) -> bool:
        return not cls.unexplained_amazon_only(
            comparison,
            allowed_codes=allowed_codes,
            ignored_attribute_roots=ignored_attribute_roots,
        )

    def _persist_response(
        self,
        plan: PayloadBuildPlan,
        attributes: Dict[str, Any],
        response: Any,
    ) -> ValidationPreviewResult:
        headers = (response or {}).get("headers") or {}
        body = (response or {}).get("body") or {}
        request_id = headers.get("x-amzn-RequestId") or headers.get("X-Amzn-RequestId")
        issues = self._extract_issues(body)
        status = "validation_preview_passed" if not issues else "validation_preview_issues"

        submission_id = self._get_submission_repo().insert_submission(
            sku=plan.sku,
            operation="create",
            status=status,
            amazon_request_id=request_id,
            marketplace_id=self.marketplace_id,
            product_type=plan.product_type,
            request_payload={
                "productType": plan.product_type,
                "attributes": attributes,
                "strictDryRun": True,
                "engine": "v2",
            },
            response_body=body,
            error_message=None,
        )

        return ValidationPreviewResult(
            sku=plan.sku,
            product_type=plan.product_type,
            status=status,
            amazon_request_id=request_id,
            issues=issues,
            submission_id=submission_id,
            error_message=None,
        )

    def _persist_failure(
        self,
        plan: PayloadBuildPlan,
        attributes: Dict[str, Any],
        exc: Exception,
    ) -> ValidationPreviewResult:
        message = str(exc) or exc.__class__.__name__
        submission_id = self._get_submission_repo().insert_submission(
            sku=plan.sku,
            operation="create",
            status="validation_preview_failed",
            amazon_request_id=None,
            marketplace_id=self.marketplace_id,
            product_type=plan.product_type,
            request_payload={
                "productType": plan.product_type,
                "attributes": attributes,
                "strictDryRun": True,
                "engine": "v2",
            },
            response_body=None,
            error_message=message,
        )
        return ValidationPreviewResult(
            sku=plan.sku,
            product_type=plan.product_type,
            status="validation_preview_failed",
            amazon_request_id=None,
            issues=[],
            submission_id=submission_id,
            error_message=message,
        )

    @staticmethod
    def _extract_issues(body: Any) -> List[Dict[str, Any]]:
        if not isinstance(body, dict):
            return []
        issues = body.get("issues")
        if not isinstance(issues, list):
            return []
        return [issue for issue in issues if isinstance(issue, dict)]

    @staticmethod
    def _root_of(path_key: str) -> str:
        head = str(path_key or "").split(".")[0]
        return head.split("{")[0]

    def _get_listings_client(self):
        if self._listings_client is None:
            from infrastructure.amazon.listings_client import AmazonListingsClient

            self._listings_client = AmazonListingsClient()
        return self._listings_client

    def _get_submission_repo(self):
        if self._submission_repo is None:
            from src.repositories.amazon_api_submission_repository import (
                AmazonAPISubmissionRepository,
            )

            self._submission_repo = AmazonAPISubmissionRepository(self.db)
        return self._submission_repo
