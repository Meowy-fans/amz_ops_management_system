"""Repository for Amazon API submission audit records."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class AmazonAPISubmissionRepository:
    """Persists Amazon SP-API submission records for audit and troubleshooting."""

    def __init__(self, db: Session):
        self.db = db

    def insert_submission(
        self,
        sku: str,
        operation: str,
        status: str,
        amazon_request_id: Optional[str] = None,
        marketplace_id: Optional[str] = None,
        product_type: Optional[str] = None,
        request_payload: Optional[Dict[str, Any]] = None,
        response_body: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> int:
        query = text("""
            INSERT INTO amazon_api_submissions (
                sku, operation, status, amazon_request_id, marketplace_id,
                product_type, request_payload, response_body, error_message,
                submitted_at
            ) VALUES (
                :sku, :operation, :status, :amazon_request_id, :marketplace_id,
                :product_type, :request_payload, :response_body, :error_message,
                :submitted_at
            )
            RETURNING id
        """)
        result = self.db.execute(query, {
            "sku": sku,
            "operation": operation,
            "status": status,
            "amazon_request_id": amazon_request_id,
            "marketplace_id": marketplace_id,
            "product_type": product_type,
            "request_payload": json.dumps(request_payload) if request_payload else None,
            "response_body": json.dumps(response_body) if response_body else None,
            "error_message": error_message,
            "submitted_at": datetime.now(timezone.utc),
        })
        self.db.commit()
        return result.scalar_one()

    def get_delayed_confirmation_candidates(
        self,
        older_than_minutes: int = 30,
        limit: int = 500,
    ) -> list[Dict[str, Any]]:
        query = text("""
            SELECT
                source.id,
                source.sku,
                source.operation,
                source.status,
                source.marketplace_id,
                source.product_type,
                source.request_payload,
                source.response_body,
                source.submitted_at
            FROM amazon_api_submissions source
            WHERE source.status IN (
                'confirmed_with_mismatch',
                'confirmed_with_issues',
                'accepted_pending_confirmation',
                'confirmation_failed'
            )
            AND source.submitted_at <= NOW() - (:older_than_minutes || ' minutes')::interval
            AND NOT EXISTS (
                SELECT 1
                FROM amazon_api_submissions child
                WHERE child.operation = 'delayed_confirmation'
                AND child.response_body->>'source_submission_id' = source.id::text
            )
            ORDER BY source.submitted_at ASC
            LIMIT :limit
        """)
        rows = self.db.execute(
            query,
            {"older_than_minutes": older_than_minutes, "limit": limit},
        ).mappings()
        return [dict(row) for row in rows]

    def get_latest_delayed_confirmation_items(
        self,
        limit: int = 500,
    ) -> list[Dict[str, Any]]:
        """Return the latest delayed confirmation row for each SKU."""
        query = text("""
            WITH latest AS (
                SELECT DISTINCT ON (sku, marketplace_id)
                    id,
                    sku,
                    operation,
                    status,
                    marketplace_id,
                    product_type,
                    request_payload,
                    response_body,
                    submitted_at,
                    response_body->>'source_submission_id' AS source_submission_id
                FROM amazon_api_submissions
                WHERE operation = 'delayed_confirmation'
                  AND response_body->>'source_submission_id' IS NOT NULL
                ORDER BY sku, marketplace_id, submitted_at DESC
            )
            SELECT
                id,
                sku,
                operation,
                status,
                marketplace_id,
                product_type,
                request_payload,
                response_body,
                submitted_at,
                source_submission_id
            FROM latest
            ORDER BY submitted_at DESC
            LIMIT :limit
        """)
        rows = self.db.execute(query, {"limit": limit}).mappings()
        return [dict(row) for row in rows]

    def get_learned_required_attributes(self, product_type: str) -> list[str]:
        """Return attributes learned from Amazon missing-required feedback."""
        query = text("""
            WITH learned AS (
                SELECT DISTINCT
                    attr.attribute_name
                FROM amazon_api_submissions,
                     jsonb_array_elements(response_body->'issues') AS issue,
                     jsonb_array_elements_text(
                         COALESCE(issue->'attributeNames', '[]'::jsonb)
                     ) AS attr(attribute_name)
                WHERE product_type = :product_type
                  AND operation = 'create'
                  AND response_body IS NOT NULL
                  AND response_body ? 'issues'
                  AND issue->>'code' = '90220'
                  AND attr.attribute_name <> ''
            )
            SELECT attribute_name
            FROM learned
            ORDER BY attribute_name
        """)
        rows = self.db.execute(query, {"product_type": product_type}).mappings()
        return [str(row["attribute_name"]) for row in rows]
