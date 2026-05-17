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
