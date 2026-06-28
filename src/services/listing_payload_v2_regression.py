"""S14 regression evaluator for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from sqlalchemy.orm import Session

from src.services.listing_payload_shadow_diff_v2 import ListingPayloadShadowDiffV2


@dataclass
class RegressionCategoryPolicy:
    """Regression acceptance policy for one product type."""

    product_type: str
    mode: str
    min_shadow_rows: int = 1
    allowed_blocking_codes: List[str] = field(default_factory=list)


class ListingPayloadV2Regression:
    """Evaluate V2 shadow evidence before cutover."""

    LIVE_CATEGORIES = ("CABINET", "HOME_MIRROR", "OTTOMAN")
    EXPLORATORY_CATEGORIES = ("CHAIR", "SOFA")
    EXPLAINABLE_BLOCKING_CODES = (
        "MISSING_REQUIRED_ATTRIBUTE_RULE",
        "LOW_CONFIDENCE_REQUIRED_ATTRIBUTE",
        "NEEDS_REVIEW_REQUIRED_ATTRIBUTE",
        "UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE",
    )

    def __init__(
        self,
        db: Session,
        diff_service: ListingPayloadShadowDiffV2 | None = None,
    ):
        self.db = db
        self.diff_service = diff_service or ListingPayloadShadowDiffV2(db)

    def evaluate(
        self,
        product_types: Iterable[str] | None = None,
        limit_per_category: int = 20,
    ) -> Dict[str, Any]:
        """Return category-level go/no-go results from shadow diff evidence."""
        policies = self._policies(product_types)
        categories = [
            self._evaluate_category(policy, limit_per_category)
            for policy in policies
        ]
        return {
            "status": "go" if all(item["decision"] == "go" for item in categories) else "no_go",
            "limit_per_category": int(limit_per_category),
            "categories": categories,
            "summary": {
                "go": sum(1 for item in categories if item["decision"] == "go"),
                "no_go": sum(1 for item in categories if item["decision"] == "no_go"),
                "total": len(categories),
            },
        }

    def _evaluate_category(
        self,
        policy: RegressionCategoryPolicy,
        limit_per_category: int,
    ) -> Dict[str, Any]:
        report = self.diff_service.report(
            product_type=policy.product_type,
            limit=limit_per_category,
        )
        latest_diffs = self._latest_diffs_by_sku(report["diffs"])
        latest_report = {
            **report,
            "count": len(latest_diffs),
            "summary": self._summary(latest_diffs),
            "diffs": latest_diffs,
        }
        reasons = self._category_reasons(policy, latest_report)
        return {
            "product_type": policy.product_type,
            "mode": policy.mode,
            "decision": "go" if not reasons else "no_go",
            "reasons": reasons,
            "shadow_rows": latest_report["count"],
            "raw_shadow_rows": report["count"],
            "shadow_summary": latest_report["summary"],
            "blocking_codes": self._blocking_codes(latest_diffs),
            "pending_review_paths": self._paths(latest_diffs, "v2_pending_review_paths"),
            "missing_required_paths": self._paths(latest_diffs, "v2_missing_required_paths"),
        }

    def _category_reasons(
        self,
        policy: RegressionCategoryPolicy,
        report: Dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        summary = report["summary"]
        if report["count"] < policy.min_shadow_rows:
            reasons.append("insufficient_shadow_evidence")
        if summary["shadow_failed"]:
            reasons.append("shadow_failures_present")

        blocking_codes = set(self._blocking_codes(report["diffs"]))
        if policy.mode == "live_regression" and blocking_codes:
            reasons.append("live_category_has_v2_blocking")
        if policy.mode == "exploratory":
            unknown = blocking_codes - set(policy.allowed_blocking_codes)
            if unknown:
                reasons.append("unexplained_v2_blocking_codes")
        return reasons

    def _policies(
        self,
        product_types: Iterable[str] | None,
    ) -> list[RegressionCategoryPolicy]:
        requested = [
            str(item or "").strip().upper()
            for item in (product_types or [])
            if str(item or "").strip()
        ]
        if not requested:
            requested = [*self.LIVE_CATEGORIES, *self.EXPLORATORY_CATEGORIES]
        policies = []
        for product_type in requested:
            if product_type in self.EXPLORATORY_CATEGORIES:
                policies.append(
                    RegressionCategoryPolicy(
                        product_type=product_type,
                        mode="exploratory",
                        allowed_blocking_codes=list(self.EXPLAINABLE_BLOCKING_CODES),
                    )
                )
            else:
                policies.append(
                    RegressionCategoryPolicy(
                        product_type=product_type,
                        mode="live_regression",
                    )
                )
        return policies

    @staticmethod
    def _blocking_codes(diffs: Iterable[Dict[str, Any]]) -> list[str]:
        codes = set()
        for diff in diffs:
            for code in diff.get("v2_blocking_codes") or []:
                if str(code or "").strip():
                    codes.add(str(code))
        return sorted(codes)

    @staticmethod
    def _latest_diffs_by_sku(diffs: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
        latest: list[Dict[str, Any]] = []
        seen: set[str] = set()
        for diff in diffs:
            key = str(diff.get("sku") or "").strip().upper()
            if not key:
                key = str(diff.get("submission_id") or "").strip()
            if key in seen:
                continue
            seen.add(key)
            latest.append(diff)
        return latest

    @staticmethod
    def _summary(diffs: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        items = list(diffs)
        return {
            "shadow_built": sum(
                1 for item in items if item.get("shadow_status") == "shadow_built"
            ),
            "shadow_failed": sum(
                1 for item in items if item.get("shadow_status") == "shadow_failed"
            ),
            "v2_blocking": sum(1 for item in items if item.get("v2_blocking_codes")),
            "with_pending_review": sum(
                1 for item in items if item.get("v2_pending_review_paths")
            ),
            "with_missing_required": sum(
                1 for item in items if item.get("v2_missing_required_paths")
            ),
        }

    @staticmethod
    def _paths(diffs: Iterable[Dict[str, Any]], key: str) -> list[str]:
        paths = set()
        for diff in diffs:
            for path in diff.get(key) or []:
                if str(path or "").strip():
                    paths.add(str(path))
        return sorted(paths)
