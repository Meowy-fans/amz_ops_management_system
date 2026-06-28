"""Repository for Layer 1 YAML rule review audit records."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class PendingRuleReviewRepository:
    """Persists operator decisions for category attribute rule review."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_decision(
        self,
        *,
        category: str,
        path_key: str,
        issue_type: str,
        decision: str,
        reviewer: str,
        detail: Optional[str] = None,
        patch_summary: Optional[Dict[str, Any]] = None,
    ) -> int:
        query = text("""
            INSERT INTO amz_listing_pending_rule_review (
                category, path_key, issue_type, decision, reviewer,
                detail, patch_summary, decided_at, updated_at
            ) VALUES (
                :category, :path_key, :issue_type, :decision, :reviewer,
                :detail, :patch_summary, NOW(), NOW()
            )
            ON CONFLICT (category, path_key, issue_type) DO UPDATE SET
                decision = EXCLUDED.decision,
                reviewer = EXCLUDED.reviewer,
                detail = EXCLUDED.detail,
                patch_summary = EXCLUDED.patch_summary,
                decided_at = NOW(),
                updated_at = NOW()
            RETURNING id
        """)
        result = self.db.execute(
            query,
            {
                "category": category,
                "path_key": path_key,
                "issue_type": issue_type,
                "decision": decision,
                "reviewer": reviewer,
                "detail": detail,
                "patch_summary": json.dumps(patch_summary or {}, default=str),
            },
        )
        row_id = int(result.scalar_one())
        self.db.commit()
        return row_id

    def list_decisions(self, category: str) -> List[Dict[str, Any]]:
        query = text("""
            SELECT id, category, path_key, issue_type, decision, reviewer,
                   detail, patch_summary, created_at, decided_at, updated_at
            FROM amz_listing_pending_rule_review
            WHERE category = :category
            ORDER BY path_key ASC, issue_type ASC
        """)
        rows = self.db.execute(query, {"category": category}).mappings()
        return [self._decode_row(dict(row)) for row in rows]

    @classmethod
    def _decode_row(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        row["patch_summary"] = cls._loads(row.get("patch_summary"))
        return row

    @staticmethod
    def _loads(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if value == "":
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
