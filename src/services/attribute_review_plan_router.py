"""Route attribute coverage review blocks to pending review storage."""

from __future__ import annotations

from typing import Any, Callable, Dict


class AttributeReviewPlanRouter:
    """Converts review-only coverage blocks into pending-review results."""

    REVIEW_ONLY_CODE = "NEEDS_REVIEW_REQUIRED_ATTRIBUTE"

    def __init__(self, service: Any):
        self.service = service

    def route(
        self,
        sku: str,
        plan: Dict[str, Any],
        result: Any,
        fallback: Callable[[str, Any], Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self._is_review_only_block(result):
            return fallback(sku, result)
        review_id = self._review_manager().persist_pending_plan(plan)
        return {
            "sku": sku,
            "status": "needs_review",
            "issues": len(result.findings),
            "review_id": review_id,
            "review_required": result.review_required,
            "blocking_codes": result.blocking_codes,
            "warning_codes": result.warning_codes,
            "attribute_coverage_findings": result.findings,
        }

    def _review_manager(self):
        if hasattr(self.service, "_review_manager_instance"):
            return self.service._review_manager_instance
        from src.services.review_manager import ReviewManager

        self.service._review_manager_instance = ReviewManager(db=self.service.db)
        return self.service._review_manager_instance

    @classmethod
    def _is_review_only_block(cls, result: Any) -> bool:
        codes = set(result.blocking_codes or [])
        return bool(result.review_required) and codes == {cls.REVIEW_ONLY_CODE}
