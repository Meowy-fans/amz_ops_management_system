"""Diff reports for V2 listing payload shadow audits."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from sqlalchemy.orm import Session

from src.repositories.amazon_api_submission_repository import (
    AmazonAPISubmissionRepository,
)


class ListingPayloadShadowDiffV2:
    """Build V1/V2 diff summaries from shadow audit rows."""

    def __init__(
        self,
        db: Session,
        submission_repo: AmazonAPISubmissionRepository | None = None,
    ):
        self.db = db
        self.submission_repo = submission_repo or AmazonAPISubmissionRepository(db)

    def report(
        self,
        product_type: str | None = None,
        sku: str | None = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Return recent shadow diffs for a product type and optional SKU."""
        normalized_product_type = self._normalize_optional(product_type)
        normalized_sku = self._normalize_optional(sku)
        rows = self.submission_repo.list_listing_payload_v2_shadow_submissions(
            product_type=normalized_product_type,
            sku=normalized_sku,
            limit=limit,
        )
        diffs = [self.diff_row(row) for row in rows]
        return {
            "product_type": normalized_product_type,
            "sku": normalized_sku,
            "limit": int(limit),
            "count": len(diffs),
            "summary": self._summary(diffs),
            "diffs": diffs,
        }

    def diff_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert one shadow audit row into a stable diff summary."""
        request = self._as_dict(row.get("request_payload"))
        response = self._as_dict(row.get("response_body"))
        v1_attributes = self._as_dict(request.get("v1_attributes"))
        v2_attributes = self._as_dict(response.get("v2_attributes"))
        v1_names = self._names(request.get("v1_attribute_names")) or sorted(
            v1_attributes
        )
        v2_names = self._names(response.get("v2_attribute_names")) or sorted(
            v2_attributes
        )
        summary = self._as_dict(response.get("summary"))
        finding_codes = self._finding_codes(response.get("v2_findings"))
        v2_blocking_codes = self._names(summary.get("blocking_codes")) or finding_codes
        return {
            "submission_id": row.get("id"),
            "sku": row.get("sku"),
            "product_type": row.get("product_type"),
            "submitted_at": str(row.get("submitted_at") or ""),
            "shadow_status": row.get("status"),
            "error_message": row.get("error_message") or "",
            "v1_status": str(request.get("v1_status") or ""),
            "v1_attribute_count": len(v1_names),
            "v2_attribute_count": len(v2_names),
            "attributes_only_in_v1": sorted(set(v1_names) - set(v2_names)),
            "attributes_only_in_v2": sorted(set(v2_names) - set(v1_names)),
            "attributes_in_both": sorted(set(v1_names) & set(v2_names)),
            "v2_required_path_count": len(self._names(response.get("v2_required_paths"))),
            "v2_missing_required_paths": self._names(
                summary.get("missing_required_paths")
            ),
            "v2_low_confidence_required_paths": self._names(
                summary.get("low_confidence_required_paths")
            ),
            "v2_pending_review_paths": self._names(
                response.get("v2_pending_review_paths")
            )
            or self._names(summary.get("pending_review_paths")),
            "v2_blocking_codes": v2_blocking_codes,
            "v2_finding_codes": finding_codes,
            "v2_condition_trace_count": int(summary.get("condition_trace_count") or 0),
        }

    @classmethod
    def _summary(cls, diffs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        items = list(diffs)
        return {
            "shadow_built": sum(1 for item in items if item["shadow_status"] == "shadow_built"),
            "shadow_failed": sum(1 for item in items if item["shadow_status"] == "shadow_failed"),
            "v2_blocking": sum(1 for item in items if item["v2_blocking_codes"]),
            "with_pending_review": sum(
                1 for item in items if item["v2_pending_review_paths"]
            ),
            "with_missing_required": sum(
                1 for item in items if item["v2_missing_required_paths"]
            ),
        }

    @staticmethod
    def _normalize_optional(value: Any) -> str | None:
        text = str(value or "").strip()
        return text.upper() if text else None

    @classmethod
    def _as_dict(cls, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _names(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return sorted({str(item) for item in value if str(item or "").strip()})

    @classmethod
    def _finding_codes(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        codes = []
        for item in value:
            data = cls._as_dict(item)
            code = str(data.get("code") or "").strip()
            if code:
                codes.append(code)
        return sorted(set(codes))
