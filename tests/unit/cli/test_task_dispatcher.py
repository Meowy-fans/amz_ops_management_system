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
