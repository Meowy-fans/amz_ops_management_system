"""Repository for audited variation resolution decisions."""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class AmazonVariationResolutionRepository:
    """Persists variation resolver decisions for audit and troubleshooting."""

    def __init__(self, db: Session):
        self.db = db

    def insert_run(
        self,
        mode: str,
        product_type: str,
        selected_theme: Optional[str],
        decision: str,
        child_skus: List[str],
        candidate_snapshot: Dict[str, Any],
        score_snapshot: Dict[str, Any],
        existing_family_snapshot: Dict[str, Any],
        finding_snapshot: List[Dict[str, Any]],
        resolver_version: str,
        parent_sku: Optional[str] = None,
    ) -> int:
        query = text("""
            INSERT INTO amazon_variation_resolution_runs (
                mode, parent_sku, product_type, selected_theme, decision,
                child_skus, candidate_snapshot, score_snapshot,
                existing_family_snapshot, finding_snapshot, resolver_version
            ) VALUES (
                :mode, :parent_sku, :product_type, :selected_theme, :decision,
                :child_skus, :candidate_snapshot, :score_snapshot,
                :existing_family_snapshot, :finding_snapshot, :resolver_version
            )
            RETURNING id
        """)
        result = self.db.execute(
            query,
            {
                "mode": mode,
                "parent_sku": parent_sku,
                "product_type": product_type,
                "selected_theme": selected_theme,
                "decision": decision,
                "child_skus": json.dumps(child_skus),
                "candidate_snapshot": json.dumps(candidate_snapshot, default=str),
                "score_snapshot": json.dumps(score_snapshot, default=str),
                "existing_family_snapshot": json.dumps(
                    existing_family_snapshot, default=str
                ),
                "finding_snapshot": json.dumps(finding_snapshot, default=str),
                "resolver_version": resolver_version,
            },
        )
        self.db.commit()
        return result.scalar_one()

    def update_run_audit(
        self,
        run_id: int,
        existing_family_snapshot: Dict[str, Any],
        finding_snapshot: List[Dict[str, Any]],
        decision: Optional[str] = None,
    ) -> None:
        """Update audit snapshots after online hierarchy checks."""
        query = text("""
            UPDATE amazon_variation_resolution_runs
            SET existing_family_snapshot = :existing_family_snapshot,
                finding_snapshot = :finding_snapshot,
                decision = COALESCE(:decision, decision)
            WHERE id = :run_id
        """)
        self.db.execute(
            query,
            {
                "run_id": int(run_id),
                "existing_family_snapshot": json.dumps(
                    existing_family_snapshot, default=str
                ),
                "finding_snapshot": json.dumps(finding_snapshot, default=str),
                "decision": decision,
            },
        )
        self.db.commit()
