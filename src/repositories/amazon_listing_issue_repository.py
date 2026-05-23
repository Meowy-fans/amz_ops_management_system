"""Repository for Amazon listing issue monitoring records."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


class AmazonListingIssueRepository:
    """Data access for listing issue scans, issues, and repair actions."""

    def __init__(self, db: Session):
        self.db = db

    def get_report_skus(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT DISTINCT "seller-sku" AS sku, asin1 AS asin
            FROM amz_all_listing_report
            WHERE "seller-sku" IS NOT NULL
              AND btrim("seller-sku") <> ''
            ORDER BY "seller-sku"
        """
        params: Dict[str, Any] = {}
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = int(limit)
        rows = self.db.execute(text(query), params).fetchall()
        return [{"sku": row.sku, "asin": row.asin} for row in rows]

    def begin_scan(self, source: str) -> int:
        result = self.db.execute(
            text("""
                INSERT INTO amazon_listing_issue_scan_runs (source, status, started_at)
                VALUES (:source, 'running', :started_at)
                RETURNING id
            """),
            {"source": source, "started_at": datetime.now(timezone.utc)},
        )
        self.db.commit()
        return result.scalar_one()

    def finish_scan(
        self,
        scan_run_id: int,
        status: str,
        checked_count: int,
        issue_count: int,
        action_count: int,
        error_message: Optional[str] = None,
    ) -> None:
        self.db.execute(
            text("""
                UPDATE amazon_listing_issue_scan_runs
                SET status = :status,
                    checked_count = :checked_count,
                    issue_count = :issue_count,
                    action_count = :action_count,
                    error_message = :error_message,
                    finished_at = :finished_at
                WHERE id = :id
            """),
            {
                "id": scan_run_id,
                "status": status,
                "checked_count": checked_count,
                "issue_count": issue_count,
                "action_count": action_count,
                "error_message": error_message,
                "finished_at": datetime.now(timezone.utc),
            },
        )
        self.db.commit()

    def upsert_issue(self, issue: Dict[str, Any]) -> int:
        result = self.db.execute(
            text("""
                INSERT INTO amazon_listing_issues (
                    scan_run_id, sku, asin, marketplace_id, product_type,
                    issue_key, issue_code, severity, message, attribute_names,
                    categories, enforcements, raw_issue, source, status,
                    first_seen_at, last_seen_at, resolved_at
                ) VALUES (
                    :scan_run_id, :sku, :asin, :marketplace_id, :product_type,
                    :issue_key, :issue_code, :severity, :message, :attribute_names,
                    :categories, :enforcements, :raw_issue, :source, 'open',
                    :now, :now, NULL
                )
                ON CONFLICT (sku, marketplace_id, issue_key) DO UPDATE SET
                    scan_run_id = EXCLUDED.scan_run_id,
                    asin = EXCLUDED.asin,
                    product_type = EXCLUDED.product_type,
                    severity = EXCLUDED.severity,
                    message = EXCLUDED.message,
                    attribute_names = EXCLUDED.attribute_names,
                    categories = EXCLUDED.categories,
                    enforcements = EXCLUDED.enforcements,
                    raw_issue = EXCLUDED.raw_issue,
                    source = EXCLUDED.source,
                    status = 'open',
                    last_seen_at = EXCLUDED.last_seen_at,
                    resolved_at = NULL
                RETURNING id
            """),
            {
                "scan_run_id": issue["scan_run_id"],
                "sku": issue["sku"],
                "asin": issue.get("asin"),
                "marketplace_id": issue["marketplace_id"],
                "product_type": issue.get("product_type"),
                "issue_key": issue["issue_key"],
                "issue_code": issue["issue_code"],
                "severity": issue["severity"],
                "message": issue["message"],
                "attribute_names": self._json(issue.get("attribute_names")),
                "categories": self._json(issue.get("categories")),
                "enforcements": self._json(issue.get("enforcements")),
                "raw_issue": self._json(issue.get("raw_issue")),
                "source": issue["source"],
                "now": datetime.now(timezone.utc),
            },
        )
        self.db.commit()
        return result.scalar_one()

    def mark_resolved_for_sku(
        self,
        sku: str,
        marketplace_id: str,
        seen_issue_keys: Iterable[str],
    ) -> int:
        keys = list(seen_issue_keys)
        params = {
            "sku": sku,
            "marketplace_id": marketplace_id,
            "resolved_at": datetime.now(timezone.utc),
        }
        if keys:
            stmt = text("""
                UPDATE amazon_listing_issues
                SET status = 'resolved', resolved_at = :resolved_at
                WHERE sku = :sku
                  AND marketplace_id = :marketplace_id
                  AND status = 'open'
                  AND issue_key NOT IN :seen_keys
            """).bindparams(bindparam("seen_keys", expanding=True))
            params["seen_keys"] = keys
        else:
            stmt = text("""
                UPDATE amazon_listing_issues
                SET status = 'resolved', resolved_at = :resolved_at
                WHERE sku = :sku
                  AND marketplace_id = :marketplace_id
                  AND status = 'open'
            """)
        result = self.db.execute(stmt, params)
        self.db.commit()
        return int(result.rowcount or 0)

    def mark_resolved_for_source(
        self,
        source: str,
        marketplace_id: str,
        seen_issue_keys: Iterable[str],
    ) -> int:
        keys = list(seen_issue_keys)
        params = {
            "source": source,
            "marketplace_id": marketplace_id,
            "resolved_at": datetime.now(timezone.utc),
        }
        if keys:
            stmt = text("""
                UPDATE amazon_listing_issues
                SET status = 'resolved', resolved_at = :resolved_at
                WHERE source = :source
                  AND marketplace_id = :marketplace_id
                  AND status = 'open'
                  AND issue_key NOT IN :seen_keys
            """).bindparams(bindparam("seen_keys", expanding=True))
            params["seen_keys"] = keys
        else:
            stmt = text("""
                UPDATE amazon_listing_issues
                SET status = 'resolved', resolved_at = :resolved_at
                WHERE source = :source
                  AND marketplace_id = :marketplace_id
                  AND status = 'open'
            """)
        result = self.db.execute(stmt, params)
        self.db.commit()
        return int(result.rowcount or 0)

    def get_open_issues(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT id, sku, asin, marketplace_id, product_type, issue_key,
                   issue_code, severity, message, attribute_names, categories,
                   enforcements, raw_issue, source, status
            FROM amazon_listing_issues
            WHERE status = 'open'
            ORDER BY
                CASE severity WHEN 'ERROR' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,
                last_seen_at DESC,
                id DESC
        """
        params: Dict[str, Any] = {}
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = int(limit)
        rows = self.db.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in rows]

    def insert_action(
        self,
        issue_id: Optional[int],
        scan_run_id: Optional[int],
        sku: str,
        marketplace_id: str,
        product_type: Optional[str],
        action_type: str,
        status: str,
        reason: str,
        request_payload: Optional[Dict[str, Any]] = None,
        response_body: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> int:
        result = self.db.execute(
            text("""
                INSERT INTO amazon_listing_issue_actions (
                    issue_id, scan_run_id, sku, marketplace_id, product_type,
                    action_type, status, reason, request_payload, response_body,
                    error_message, executed_at
                ) VALUES (
                    :issue_id, :scan_run_id, :sku, :marketplace_id, :product_type,
                    :action_type, :status, :reason, :request_payload, :response_body,
                    :error_message, :executed_at
                )
                RETURNING id
            """),
            {
                "issue_id": issue_id,
                "scan_run_id": scan_run_id,
                "sku": sku,
                "marketplace_id": marketplace_id,
                "product_type": product_type,
                "action_type": action_type,
                "status": status,
                "reason": reason,
                "request_payload": self._json(request_payload),
                "response_body": self._json(response_body),
                "error_message": error_message,
                "executed_at": (
                    datetime.now(timezone.utc)
                    if status in {"submitted", "failed", "skipped"}
                    else None
                ),
            },
        )
        self.db.commit()
        return result.scalar_one()

    @staticmethod
    def _json(value: Any) -> Optional[str]:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)
