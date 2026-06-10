"""Delete legacy Amazon listings that lack Giga SKU mapping."""

import logging
import time
from typing import Any, Dict, List, Optional

from src.services.progress_reporter import ProgressReporter
from src.repositories.amazon_api_submission_repository import (
    AmazonAPISubmissionRepository,
)

logger = logging.getLogger(__name__)


class AmazonListingCleanupService:
    """Identifies and deletes live legacy listings without meow_sku_map Giga mapping."""

    def __init__(
        self,
        db,
        reporter: Optional[ProgressReporter] = None,
        listings_client: Any = None,
        submission_repo: Any = None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self.submission_repo = submission_repo or AmazonAPISubmissionRepository(db)

    def delete_orphan_listings(
        self,
        dry_run: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Find and delete live legacy listings that have no Giga mapping in meow_sku_map."""
        candidates = self._get_deletable_skus(limit=limit)
        if not candidates:
            self.reporter.emit("No deletable orphan listings found.")
            return []

        self.reporter.emit(f"Found {len(candidates)} deletable orphan listings:")
        for item in candidates:
            self.reporter.emit(f"  {item['sku']}  (cat={item['category']})")
        self.reporter.emit("")

        if dry_run:
            self.reporter.emit(
                f"DRY RUN: {len(candidates)} SKU(s) would be deleted. "
                "Use --no-dry-run to execute."
            )
            for item in candidates:
                self.submission_repo.insert_submission(
                    sku=item["sku"],
                    operation="delete_listing",
                    status="dry_run",
                    product_type=item.get("product_type", "PRODUCT"),
                )
            return [{"sku": item["sku"], "status": "dry_run"} for item in candidates]

        client = self._listings_client()
        results = []
        for i, item in enumerate(candidates):
            result = self._delete_one(client, item, i + 1, len(candidates))
            results.append(result)

        self._emit_summary(results)
        return results

    def _get_deletable_skus(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        from sqlalchemy import text

        query = """
            WITH legacy_unmapped_live AS (
                SELECT cache.sku
                FROM amazon_listing_items_cache cache
                LEFT JOIN meow_sku_map m ON cache.sku = m.meow_sku
                WHERE m.meow_sku IS NULL
                  AND cache.listing_status ?| ARRAY['BUYABLE', 'DISCOVERABLE']
                  AND cache.sku NOT LIKE 'meow%'
                  AND cache.sku NOT LIKE 'PARENT-%'
                  AND cache.sku NOT LIKE '%-PARENT'
            )
            SELECT
                l.sku,
                'legacy_unmapped' AS category,
                COALESCE(
                    NULLIF(cache.product_type, ''),
                    cache.summaries->0->>'productType',
                    'PRODUCT'
                ) AS product_type
            FROM legacy_unmapped_live l
            JOIN amazon_listing_items_cache cache ON cache.sku = l.sku
            ORDER BY l.sku
        """
        if limit:
            query += f" LIMIT {int(limit)}"

        rows = self.db.execute(text(query)).mappings()
        return [dict(row) for row in rows]

    def _delete_one(
        self,
        client: Any,
        item: Dict[str, Any],
        idx: int,
        total: int,
    ) -> Dict[str, Any]:
        sku = item["sku"]
        product_type = item.get("product_type", "PRODUCT")
        self.reporter.emit(f"  [{idx}/{total}] Deleting {sku} ...")

        try:
            resp = client.delete_listings_item(sku=sku)
            body = resp.get("body", {})
            status = body.get("status", "ACCEPTED")
            issues = body.get("issues") or []

            db_status = "deleted" if status == "ACCEPTED" and not issues else "deleted_with_issues"
            self.submission_repo.insert_submission(
                sku=sku,
                operation="delete_listing",
                status=db_status,
                product_type=product_type,
                response_body=body,
            )

            if status == "ACCEPTED":
                self._cleanup_sku_map(sku)
                self.reporter.emit("OK")

            result = {"sku": sku, "status": db_status}
        except Exception as exc:
            msg = str(exc)[:120]
            self.submission_repo.insert_submission(
                sku=sku,
                operation="delete_listing",
                status="delete_failed",
                product_type=product_type,
                error_message=msg,
            )
            self.reporter.emit(f"FAILED: {msg}")
            result = {"sku": sku, "status": "delete_failed", "error": msg}

        if idx < total:
            time.sleep(0.25)
        return result

    def _cleanup_sku_map(self, sku: str) -> None:
        """Remove the meow_sku_map entry for a deleted listing if it exists."""
        from sqlalchemy import text

        result = self.db.execute(
            text("DELETE FROM meow_sku_map WHERE meow_sku = :sku"),
            {"sku": sku},
        )
        if result.rowcount and result.rowcount > 0:
            self.db.commit()
            logger.info("Removed meow_sku_map entry for deleted SKU %s", sku)

    def _listings_client(self):
        if self._listings_client_instance is not None:
            return self._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self._listings_client_instance = AmazonListingsClient()
        return self._listings_client_instance

    def _emit_summary(self, results: List[Dict[str, Any]]) -> None:
        counts: Dict[str, int] = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        self.reporter.emit(f"\n{'=' * 70}")
        self.reporter.emit(f"Cleanup complete: {len(results)} SKU(s)")
        for status, count in sorted(counts.items()):
            self.reporter.emit(f"  {status}: {count}")
        self.reporter.emit(f"{'=' * 70}")
