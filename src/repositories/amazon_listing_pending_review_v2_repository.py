"""Repository for V2 path-level pending review records."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class AmazonListingPendingReviewV2Repository:
    """Persists V2 path-level review items (one row per path)."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_pending_paths(self, items: List[Dict[str, Any]]) -> List[int]:
        if not items:
            return []
        query = text("""
            INSERT INTO amz_listing_pending_review_v2 (
                category, sku, parent_sku, path_key, path_key_version,
                attribute, display_label, value, evidence,
                confidence_label, confidence_score, route,
                review_status, plan_snapshot
            ) VALUES (
                :category, :sku, :parent_sku, :path_key, :path_key_version,
                :attribute, :display_label, :value, :evidence,
                :confidence_label, :confidence_score, :route,
                'pending', :plan_snapshot
            )
            ON CONFLICT (category, sku, path_key, path_key_version) DO UPDATE SET
                parent_sku = EXCLUDED.parent_sku,
                attribute = EXCLUDED.attribute,
                display_label = EXCLUDED.display_label,
                value = EXCLUDED.value,
                evidence = EXCLUDED.evidence,
                confidence_label = EXCLUDED.confidence_label,
                confidence_score = EXCLUDED.confidence_score,
                route = EXCLUDED.route,
                plan_snapshot = EXCLUDED.plan_snapshot,
                review_status = 'pending',
                reviewer = NULL,
                verdict = NULL,
                decided_at = NULL,
                updated_at = NOW()
            RETURNING id
        """)
        ids: List[int] = []
        for item in items:
            result = self.db.execute(query, self._params_for(item))
            ids.append(int(result.scalar_one()))
        self.db.commit()
        return ids

    def list_pending(
        self,
        category: Optional[str] = None,
        status: str = "pending",
        route: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses = ["review_status = :status"]
        params: Dict[str, Any] = {"limit": int(limit), "status": status}
        if category:
            clauses.append("category = :category")
            params["category"] = category
        if route:
            clauses.append("route = :route")
            params["route"] = route
        where = "WHERE " + " AND ".join(clauses)
        query = text(f"""
            SELECT id, category, sku, parent_sku, path_key, path_key_version,
                   attribute, display_label, value, evidence,
                   confidence_label, confidence_score, route,
                   review_status, reviewer, verdict, decided_at,
                   plan_snapshot, created_at, updated_at
            FROM amz_listing_pending_review_v2
            {where}
            ORDER BY created_at ASC
            LIMIT :limit
        """)
        rows = self.db.execute(query, params).mappings()
        return [self._decode_row(dict(row)) for row in rows]

    def list_for_sku(self, category: str, sku: str) -> List[Dict[str, Any]]:
        query = text("""
            SELECT id, category, sku, parent_sku, path_key, path_key_version,
                   attribute, display_label, value, evidence,
                   confidence_label, confidence_score, route,
                   review_status, reviewer, verdict, decided_at,
                   plan_snapshot, created_at, updated_at
            FROM amz_listing_pending_review_v2
            WHERE category = :category AND sku = :sku
            ORDER BY path_key ASC
        """)
        rows = self.db.execute(
            query, {"category": category, "sku": sku}
        ).mappings()
        return [self._decode_row(dict(row)) for row in rows]

    def save_decision(
        self,
        review_id: int,
        decision: str,
        reviewer: str,
        verdict: Dict[str, Any],
        review_status: str,
    ) -> None:
        query = text("""
            UPDATE amz_listing_pending_review_v2
            SET review_status = :review_status,
                reviewer = :reviewer,
                verdict = :verdict,
                decided_at = NOW(),
                updated_at = NOW()
            WHERE id = :review_id
        """)
        self.db.execute(
            query,
            {
                "review_id": int(review_id),
                "review_status": review_status,
                "reviewer": reviewer,
                "verdict": json.dumps(verdict, default=str),
            },
        )
        self.db.commit()

    def list_approved_for_sku(
        self,
        category: str,
        sku: str,
    ) -> List[Dict[str, Any]]:
        query = text("""
            SELECT id, category, sku, parent_sku, path_key, path_key_version,
                   attribute, display_label, value, evidence,
                   confidence_label, confidence_score, route,
                   review_status, reviewer, verdict, decided_at,
                   plan_snapshot, created_at, updated_at
            FROM amz_listing_pending_review_v2
            WHERE category = :category AND sku = :sku
              AND review_status = 'completed'
            ORDER BY path_key ASC
        """)
        rows = self.db.execute(
            query, {"category": category, "sku": sku}
        ).mappings()
        return [self._decode_row(dict(row)) for row in rows]

    def list_completed_skus(
        self,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, str]]:
        clauses = ["review_status = 'completed'"]
        params: Dict[str, Any] = {"limit": int(limit)}
        if category:
            clauses.append("category = :category")
            params["category"] = category
        where = "WHERE " + " AND ".join(clauses)
        query = text(f"""
            SELECT DISTINCT category, sku, parent_sku
            FROM amz_listing_pending_review_v2
            {where}
            ORDER BY sku ASC
            LIMIT :limit
        """)
        rows = self.db.execute(query, params).mappings()
        return [dict(row) for row in rows]

    def get_path_accuracy(
        self,
        product_type: str,
        path_key: str,
        min_samples: int = 10,
    ) -> Optional[float]:
        query = text("""
            WITH path_stats AS (
                SELECT
                    COUNT(*) AS sample_count,
                    SUM(
                        CASE
                            WHEN reviewer = 'attribute_review_agent' THEN 1
                            ELSE 0
                        END
                    ) AS approved_count
                FROM amz_listing_pending_review_v2
                WHERE category = :product_type
                  AND path_key = :path_key
                  AND review_status = 'completed'
            )
            SELECT
                CASE
                    WHEN sample_count >= :min_samples
                    THEN approved_count::float / NULLIF(sample_count, 0)
                    ELSE NULL
                END AS accuracy
            FROM path_stats
        """)
        row = self.db.execute(
            query,
            {
                "product_type": product_type,
                "path_key": path_key,
                "min_samples": int(min_samples),
            },
        ).mappings().first()
        if not row or row["accuracy"] is None:
            return None
        return float(row["accuracy"])

    @staticmethod
    def _params_for(item: Dict[str, Any]) -> Dict[str, Any]:
        value = item.get("value")
        return {
            "category": item["category"],
            "sku": item["sku"],
            "parent_sku": item.get("parent_sku"),
            "path_key": item["path_key"],
            "path_key_version": item["path_key_version"],
            "attribute": item.get("attribute") or _attribute_from_path_key(item["path_key"]),
            "display_label": item.get("display_label"),
            "value": json.dumps(value, default=str) if value is not None else None,
            "evidence": item.get("evidence"),
            "confidence_label": item.get("confidence_label"),
            "confidence_score": item.get("confidence_score"),
            "route": item["route"],
            "plan_snapshot": json.dumps(item.get("plan_snapshot") or {}, default=str),
        }

    @classmethod
    def _decode_row(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("value", "verdict", "plan_snapshot"):
            row[key] = cls._loads(row.get(key))
        return row

    @staticmethod
    def _loads(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if value == "":
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value


def _attribute_from_path_key(path_key: str) -> str:
    head = str(path_key or "").split(".")[0]
    return head.split("{")[0]
