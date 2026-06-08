import pytest

from src.cli import task_dispatcher
from src.cli.task_dispatcher import UnknownTaskError, dispatch_task


def test_dispatch_unknown_task_raises():
    with pytest.raises(UnknownTaskError):
        dispatch_task(db=object(), task="missing-task")


def test_dispatch_generate_listing_returns_service_result(monkeypatch):
    class Service:
        def __init__(self, db):
            self.db = db

        def generate_listings_by_category(self, category):
            return {"success": True, "category": category}

    monkeypatch.setitem(task_dispatcher.TASK_HANDLERS, "noop", lambda db, **kwargs: "ok")
    monkeypatch.setattr("src.services.product_listing_service.ProductListingService", Service)

    assert dispatch_task(object(), "noop") == "ok"
    assert dispatch_task(
        object(),
        "generate-listing",
        category="CABINET",
        return_listing_result=True,
    ) == {"success": True, "category": "CABINET"}


def test_dispatch_generate_listing_uses_cli_handler_without_return(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_generate_listing",
        lambda db, category=None: calls.append((db, category)),
    )

    db = object()
    result = dispatch_task(db, "generate-listing", category="CABINET")

    assert result is None
    assert calls == [(db, "CABINET")]


def test_dispatch_sync_amz_report_api_uses_cli_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_sync_amazon_report_api",
        lambda db: calls.append(db),
    )

    db = object()
    result = dispatch_task(db, "sync-amz-report-api")

    assert result is None
    assert calls == [db]


def test_dispatch_sync_listing_issues_passes_dry_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_sync_listing_issues",
        lambda db, dry_run=True: calls.append((db, dry_run)),
    )

    db = object()
    result = dispatch_task(db, "sync-listing-issues", dry_run=False)

    assert result is None
    assert calls == [(db, False)]


def test_dispatch_confirm_price_inventory_api_uses_cli_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_confirm_price_inventory_api",
        lambda db: calls.append(db),
    )

    db = object()
    result = dispatch_task(db, "confirm-price-inventory-api")

    assert result is None
    assert calls == [db]


def test_dispatch_sync_confirmation_listing_issues_passes_dry_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_sync_confirmation_listing_issues",
        lambda db, dry_run=True: calls.append((db, dry_run)),
    )

    db = object()
    result = dispatch_task(db, "sync-confirmation-listing-issues", dry_run=False)

    assert result is None
    assert calls == [(db, False)]


def test_dispatch_repair_listing_issues_passes_dry_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_repair_listing_issues",
        lambda db, dry_run=True: calls.append((db, dry_run)),
    )

    db = object()
    result = dispatch_task(db, "repair-listing-issues", dry_run=False)

    assert result is None
    assert calls == [(db, False)]


def test_dispatch_confirm_listing_issue_repairs_uses_cli_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_confirm_listing_issue_repairs",
        lambda db: calls.append(db),
    )

    db = object()
    result = dispatch_task(db, "confirm-listing-issue-repairs")

    assert result is None
    assert calls == [db]
