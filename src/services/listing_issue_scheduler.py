"""Optional background scheduler for Amazon listing issue sync."""
import logging
import os
import threading
import time
from typing import Callable

from src.services.progress_reporter import NullProgressReporter

logger = logging.getLogger(__name__)


def start_listing_issue_scheduler(session_factory: Callable) -> bool:
    """Start the listing issue scheduler when explicitly enabled.

    Returns True when a background thread was started.
    """
    enabled = os.getenv("LISTING_ISSUE_SCHEDULER_ENABLED", "false").lower()
    if enabled not in {"1", "true", "yes"}:
        return False

    interval = int(os.getenv("LISTING_ISSUE_SYNC_INTERVAL_SECONDS", "3600"))
    limit_text = os.getenv("LISTING_ISSUE_SYNC_LIMIT")
    limit = int(limit_text) if limit_text else None
    include_report = os.getenv("LISTING_ISSUE_INCLUDE_SUPPRESSED_REPORT", "true").lower()
    dry_run = os.getenv("LISTING_ISSUE_REPAIR_DRY_RUN", "true").lower()

    thread = threading.Thread(
        target=_scheduler_loop,
        args=(
            session_factory,
            max(interval, 300),
            limit,
            include_report in {"1", "true", "yes"},
            dry_run not in {"0", "false", "no"},
        ),
        name="listing-issue-scheduler",
        daemon=True,
    )
    thread.start()
    logger.info("Amazon listing issue scheduler started interval=%ss", max(interval, 300))
    return True


def _scheduler_loop(
    session_factory: Callable,
    interval_seconds: int,
    limit: int | None,
    include_suppressed_report: bool,
    dry_run: bool,
) -> None:
    from src.services.amazon_listing_issue_sync_service import (
        AmazonListingIssueSyncService,
    )

    while True:
        try:
            with session_factory() as db:
                service = AmazonListingIssueSyncService(
                    db,
                    reporter=NullProgressReporter(),
                )
                service.sync_and_repair(
                    limit=limit,
                    dry_run=dry_run,
                    include_suppressed_report=include_suppressed_report,
                )
        except Exception as exc:
            logger.error("Scheduled listing issue sync failed: %s", exc, exc_info=True)
        time.sleep(interval_seconds)
