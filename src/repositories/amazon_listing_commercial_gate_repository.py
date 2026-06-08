"""Repository for auditable commercial gate decisions."""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class AmazonListingCommercialGateRepository:
    """Persists commercial gate decisions for listing auditability."""

    def __init__(self, db: Session):
        self.db = db

    def insert_run(
        self,
        sku: str,
        product_type: str,
        gate_version: str,
        decision: str,
        blocking_codes: List[str],
        warning_codes: List[str],
        input_snapshot: Dict[str, Any],
        rule_snapshot: Dict[str, Any],
        finding_snapshot: List[Dict[str, Any]],
        vendor_sku: Optional[str] = None,
    ) -> int:
        query = text("""
            INSERT INTO amazon_listing_commercial_gate_runs (
                sku, vendor_sku, product_type, gate_version, decision,
                blocking_codes, warning_codes, input_snapshot, rule_snapshot,
                finding_snapshot
            ) VALUES (
                :sku, :vendor_sku, :product_type, :gate_version, :decision,
                :blocking_codes, :warning_codes, :input_snapshot, :rule_snapshot,
                :finding_snapshot
            )
            RETURNING id
        """)
        result = self.db.execute(
            query,
            {
                "sku": sku,
                "vendor_sku": vendor_sku,
                "product_type": product_type,
                "gate_version": gate_version,
                "decision": decision,
                "blocking_codes": json.dumps(blocking_codes),
                "warning_codes": json.dumps(warning_codes),
                "input_snapshot": json.dumps(input_snapshot, default=str),
                "rule_snapshot": json.dumps(rule_snapshot, default=str),
                "finding_snapshot": json.dumps(finding_snapshot, default=str),
            },
        )
        self.db.commit()
        return result.scalar_one()
