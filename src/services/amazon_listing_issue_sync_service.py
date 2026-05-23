"""Amazon listing issue polling and repair orchestration."""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.services.amazon_listing_issue_payloads import (
    normalize_issue,
    parse_suppressed_report,
)
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class AmazonListingIssueSyncService:
    """Polls official Amazon APIs for listing issues and queues repairs."""

    LISTINGS_ITEM_SOURCE = "listings_items"
    SUPPRESSED_REPORT_SOURCE = "suppressed_report"

    def __init__(
        self,
        db: Session,
        reporter: Optional[ProgressReporter] = None,
        listings_client: Any = None,
        reports_client: Any = None,
        issue_repo: Any = None,
        repair_service: Any = None,
        marketplace_id: Optional[str] = None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self._reports_client_instance = reports_client
        self._issue_repo_instance = issue_repo
        self._repair_service_instance = repair_service
        self.marketplace_id = marketplace_id or self._default_marketplace_id()

    def sync_and_repair(
        self,
        limit: Optional[int] = None,
        dry_run: bool = True,
        include_suppressed_report: bool = True,
    ) -> Dict[str, Any]:
        """Run one issue scan and start the repair workflow."""
        repo = self._issue_repo()
        scan_run_id = repo.begin_scan(self.LISTINGS_ITEM_SOURCE)
        checked_count = 0
        synced_issues: List[Dict[str, Any]] = []
        action_results: List[Dict[str, Any]] = []
        errors: List[str] = []

        try:
            sku_rows = repo.get_report_skus(limit=limit)
            self.reporter.emit(f"Scanning {len(sku_rows)} Amazon SKU(s) for listing issues...")
            for row in sku_rows:
                sku = row["sku"]
                checked_count += 1
                try:
                    item_issues = self._fetch_listing_item_issues(
                        sku,
                        fallback_asin=row.get("asin"),
                    )
                except Exception as exc:
                    message = f"{sku}: {exc}"
                    errors.append(message)
                    logger.warning("Failed to fetch listing issues for %s: %s", sku, exc)
                    continue
                seen_keys = []
                for issue in item_issues:
                    issue["scan_run_id"] = scan_run_id
                    issue_id = repo.upsert_issue(issue)
                    issue["id"] = issue_id
                    seen_keys.append(issue["issue_key"])
                    synced_issues.append(issue)
                repo.mark_resolved_for_sku(sku, self.marketplace_id, seen_keys)

            if include_suppressed_report:
                try:
                    suppressed_issues = self._sync_suppressed_report(scan_run_id)
                    synced_issues.extend(suppressed_issues)
                except Exception as exc:
                    errors.append(f"suppressed_report: {exc}")
                    logger.warning("Suppressed listings report sync failed: %s", exc)

            open_issues = repo.get_open_issues()
            action_results = self._repair_service().plan_and_execute(
                open_issues,
                scan_run_id=scan_run_id,
                dry_run=dry_run,
            )
            repo.finish_scan(
                scan_run_id=scan_run_id,
                status="partial_success" if errors else "success",
                checked_count=checked_count,
                issue_count=len(synced_issues),
                action_count=len(action_results),
                error_message="; ".join(errors[:5]) if errors else None,
            )
            self._emit_summary(checked_count, synced_issues, action_results, dry_run, errors)
            return {
                "scan_run_id": scan_run_id,
                "checked_count": checked_count,
                "issue_count": len(synced_issues),
                "action_count": len(action_results),
                "error_count": len(errors),
                "dry_run": dry_run,
            }
        except Exception as exc:
            repo.finish_scan(
                scan_run_id=scan_run_id,
                status="failed",
                checked_count=checked_count,
                issue_count=len(synced_issues),
                action_count=len(action_results),
                error_message=str(exc),
            )
            logger.error("Amazon listing issue sync failed: %s", exc, exc_info=True)
            raise

    def _fetch_listing_item_issues(
        self,
        sku: str,
        fallback_asin: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        response = self._listings_client().get_listings_item(
            sku=sku,
            included_data=["summaries", "issues", "productTypes"],
        )
        body = response["body"]
        summary = (body.get("summaries") or [{}])[0]
        product_type = (body.get("productTypes") or [{}])[0].get("productType")
        asin = summary.get("asin") or fallback_asin
        item_name = summary.get("itemName")

        issues = []
        for raw_issue in body.get("issues") or []:
            issues.append(
                normalize_issue(
                    sku=sku,
                    asin=asin,
                    marketplace_id=self.marketplace_id,
                    product_type=product_type,
                    item_name=item_name,
                    raw_issue=raw_issue,
                    source=self.LISTINGS_ITEM_SOURCE,
                )
            )
        return issues

    def _sync_suppressed_report(self, scan_run_id: int) -> List[Dict[str, Any]]:
        reports_client = self._reports_client()
        report_id = reports_client.create_suppressed_listings_report()
        document_id = reports_client.wait_for_report(report_id)
        document = reports_client.get_report_document(document_id)
        report_text = reports_client.download_report_document(document)

        synced = []
        repo = self._issue_repo()
        seen_keys = []
        for issue in parse_suppressed_report(
            report_text,
            marketplace_id=self.marketplace_id,
            source=self.SUPPRESSED_REPORT_SOURCE,
        ):
            issue["scan_run_id"] = scan_run_id
            issue_id = repo.upsert_issue(issue)
            issue["id"] = issue_id
            seen_keys.append(issue["issue_key"])
            synced.append(issue)
        repo.mark_resolved_for_source(
            self.SUPPRESSED_REPORT_SOURCE,
            self.marketplace_id,
            seen_keys,
        )
        return synced

    def _emit_summary(
        self,
        checked_count: int,
        issues: List[Dict[str, Any]],
        actions: List[Dict[str, Any]],
        dry_run: bool,
        errors: Optional[List[str]] = None,
    ) -> None:
        self.reporter.emit("\n" + "=" * 70)
        mode = "DRY RUN" if dry_run else "LIVE"
        self.reporter.emit(f"Amazon Listing Issue Sync Complete - {mode}")
        self.reporter.emit(f"Checked SKUs: {checked_count}")
        self.reporter.emit(f"Synced issues: {len(issues)}")
        self.reporter.emit(f"Repair actions: {len(actions)}")
        if errors:
            self.reporter.emit(f"Partial errors: {len(errors)}")
        for action in actions[:10]:
            self.reporter.emit(
                f"  {action.get('status')} {action.get('sku')} "
                f"{action.get('issue_code', '-')} -> {action.get('action_type', '-')}"
            )
        if len(actions) > 10:
            self.reporter.emit(f"  ... {len(actions) - 10} more action(s)")
        self.reporter.emit("=" * 70)

    def _listings_client(self):
        if self._listings_client_instance is not None:
            return self._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self._listings_client_instance = AmazonListingsClient()
        return self._listings_client_instance

    def _reports_client(self):
        if self._reports_client_instance is not None:
            return self._reports_client_instance
        from infrastructure.amazon.reports_client import AmazonReportsClient

        self._reports_client_instance = AmazonReportsClient()
        return self._reports_client_instance

    def _issue_repo(self):
        if self._issue_repo_instance is not None:
            return self._issue_repo_instance
        from src.repositories.amazon_listing_issue_repository import (
            AmazonListingIssueRepository,
        )

        self._issue_repo_instance = AmazonListingIssueRepository(self.db)
        return self._issue_repo_instance

    def _repair_service(self):
        if self._repair_service_instance is not None:
            return self._repair_service_instance
        from src.services.amazon_listing_issue_repair_service import (
            AmazonListingIssueRepairService,
        )

        self._repair_service_instance = AmazonListingIssueRepairService(
            self.db,
            reporter=self.reporter,
            issue_repo=self._issue_repo(),
        )
        return self._repair_service_instance

    @staticmethod
    def _default_marketplace_id() -> str:
        try:
            from infrastructure.amazon.config import AmazonConfig

            return AmazonConfig.MARKETPLACE_ID
        except Exception:
            return "ATVPDKIKX0DER"
