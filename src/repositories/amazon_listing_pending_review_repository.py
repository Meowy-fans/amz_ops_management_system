"""Repository for pending listing attribute review records."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class AmazonListingPendingReviewRepository:
    """Persists reviewable listing plans that should not be submitted yet."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_pending(
        self,
        category: str,
        sku: str,
        parent_sku: Optional[str],
        plan_snapshot: Dict[str, Any],
        pending_items: List[Dict[str, Any]],
    ) -> int:
        query = text("""
            INSERT INTO amz_listing_pending_review (
                category, sku, parent_sku, plan_snapshot, pending_items,
                review_decisions, review_status
            ) VALUES (
                :category, :sku, :parent_sku, :plan_snapshot, :pending_items,
                '[]'::jsonb, 'pending'
            )
            ON CONFLICT (category, sku) DO UPDATE SET
                parent_sku = EXCLUDED.parent_sku,
                plan_snapshot = EXCLUDED.plan_snapshot,
                pending_items = EXCLUDED.pending_items,
                review_status = 'pending',
                updated_at = NOW()
            RETURNING id
        """)
        result = self.db.execute(
            query,
            {
                "category": category,
                "sku": sku,
                "parent_sku": parent_sku,
                "plan_snapshot": json.dumps(plan_snapshot, default=str),
                "pending_items": json.dumps(pending_items, default=str),
            },
        )
        self.db.commit()
        return int(result.scalar_one())

    def list_reviews(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: Dict[str, Any] = {"limit": int(limit)}
        if category:
            clauses.append("category = :category")
            params["category"] = category
        if status:
            clauses.append("review_status = :status")
            params["status"] = status
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = text(f"""
            SELECT id, category, sku, parent_sku, plan_snapshot, pending_items,
                   review_decisions, review_status, created_at, updated_at
            FROM amz_listing_pending_review
            {where}
            ORDER BY created_at ASC
            LIMIT :limit
        """)
        rows = self.db.execute(query, params).mappings()
        return [self._decode_row(dict(row)) for row in rows]

    def save_decisions(
        self,
        review_id: int,
        decisions: List[Dict[str, Any]],
        status: str,
    ) -> None:
        query = text("""
            UPDATE amz_listing_pending_review
            SET review_decisions = :review_decisions,
                review_status = :review_status,
                updated_at = NOW()
            WHERE id = :review_id
        """)
        self.db.execute(
            query,
            {
                "review_id": int(review_id),
                "review_decisions": json.dumps(decisions, default=str),
                "review_status": status,
            },
        )
        self.db.commit()

    def get_attribute_accuracy(
        self,
        product_type: str,
        attribute: str,
        min_samples: int = 10,
    ) -> Optional[float]:
        query = text("""
            WITH decisions AS (
                SELECT jsonb_array_elements(review_decisions) AS decision
                FROM amz_listing_pending_review
                WHERE category = :product_type
                  AND review_status = 'completed'
                  AND review_decisions IS NOT NULL
            ),
            stats AS (
                SELECT
                    COUNT(*) AS sample_count,
                    SUM(
                        CASE
                            WHEN decision->>'decision' = 'approved' THEN 1
                            ELSE 0
                        END
                    ) AS approved_count
                FROM decisions
                WHERE decision->>'attribute' = :attribute
            )
            SELECT
                CASE
                    WHEN sample_count >= :min_samples
                    THEN approved_count::float / NULLIF(sample_count, 0)
                    ELSE NULL
                END AS accuracy
            FROM stats
        """)
        row = self.db.execute(
            query,
            {
                "product_type": product_type,
                "attribute": attribute,
                "min_samples": int(min_samples),
            },
        ).mappings().first()
        if not row or row["accuracy"] is None:
            return None
        return float(row["accuracy"])

    @classmethod
    def _decode_row(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("plan_snapshot", "pending_items", "review_decisions"):
            row[key] = cls._loads(row.get(key))
        return row

    @staticmethod
    def _loads(value: Any) -> Any:
        if value in (None, ""):
            return [] if value == "" else value
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)
