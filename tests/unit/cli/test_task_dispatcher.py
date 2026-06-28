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

        def generate_listings_via_api(
            self,
            category_name,
            dry_run=True,
            validation_only=False,
            sku_list=None,
            sku_file=None,
            only_not_on_amazon=False,
        ):
            return {
                "success": True,
                "category": category_name,
                "dry_run": dry_run,
                "validation_only": validation_only,
                "sku_list": sku_list,
                "sku_file": sku_file,
                "only_not_on_amazon": only_not_on_amazon,
            }

    monkeypatch.setitem(task_dispatcher.TASK_HANDLERS, "noop", lambda db, **kwargs: "ok")
    monkeypatch.setattr("src.services.product_listing_service.ProductListingService", Service)

    assert dispatch_task(object(), "noop") == "ok"
    assert dispatch_task(
        object(),
        "generate-listing",
        category="CABINET",
        return_listing_result=True,
    ) == {
        "success": True,
        "category": "CABINET",
        "dry_run": True,
        "validation_only": False,
        "sku_list": None,
        "sku_file": None,
        "only_not_on_amazon": False,
    }


def test_dispatch_generate_listing_return_result_passes_strict_validation(monkeypatch):
    class Service:
        def __init__(self, db):
            self.db = db

        def generate_listings_via_api(
            self,
            category_name,
            dry_run=True,
            validation_only=False,
            sku_list=None,
            sku_file=None,
            only_not_on_amazon=False,
        ):
            return {
                "success": True,
                "category": category_name,
                "dry_run": dry_run,
                "validation_only": validation_only,
            }

    monkeypatch.setattr("src.services.product_listing_service.ProductListingService", Service)

    assert dispatch_task(
        object(),
        "generate-listing",
        category="CABINET",
        return_listing_result=True,
        strict_validation=True,
    ) == {
        "success": True,
        "category": "CABINET",
        "dry_run": True,
        "validation_only": True,
    }


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


def test_dispatch_auto_discover_category_passes_scope_and_dry_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_auto_discover_category",
        lambda db, category_code=None, all_unmapped=False, dry_run=True: calls.append(
            (db, category_code, all_unmapped, dry_run)
        ),
    )

    db = object()
    result = dispatch_task(
        db,
        "auto-discover-category",
        category_code="10027",
        all_unmapped=True,
        dry_run=False,
    )

    assert result is None
    assert calls == [(db, "10027", True, False)]


def test_dispatch_generate_attribute_rules_passes_product_type(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_generate_attribute_rules",
        lambda db, product_type=None: calls.append((db, product_type)),
    )

    db = object()
    result = dispatch_task(
        db,
        "generate-attribute-rules",
        product_type="SOFA",
    )

    assert result is None
    assert calls == [(db, "SOFA")]


def test_dispatch_analyze_listing_requirements_v2_passes_product_type_and_sku(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_analyze_listing_requirements_v2",
        lambda db, product_type=None, sku_list=None: calls.append(
            (db, product_type, sku_list)
        ),
    )

    db = object()
    result = dispatch_task(
        db,
        "analyze-listing-requirements-v2",
        product_type="CHAIR",
        sku_list=["SKU1"],
    )

    assert result is None
    assert calls == [(db, "CHAIR", ["SKU1"])]


def test_dispatch_report_listing_shadow_diff_v2_passes_filters(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_report_listing_shadow_diff_v2",
        lambda db, product_type=None, sku_list=None: calls.append(
            (db, product_type, sku_list)
        ),
    )

    db = object()
    result = dispatch_task(
        db,
        "report-listing-shadow-diff-v2",
        product_type="CHAIR",
        sku_list=["SKU1"],
    )

    assert result is None
    assert calls == [(db, "CHAIR", ["SKU1"])]


def test_dispatch_evaluate_listing_v2_regression_passes_product_type(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_evaluate_listing_v2_regression",
        lambda db, product_type=None: calls.append((db, product_type)),
    )

    db = object()
    result = dispatch_task(
        db,
        "evaluate-listing-v2-regression",
        product_type="CHAIR",
    )

    assert result is None
    assert calls == [(db, "CHAIR")]


def test_dispatch_generate_listing_api_passes_strict_validation(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_generate_listing_api",
        lambda db, category=None, dry_run=True, strict_validation=False,
        sku_list=None, sku_file=None, only_not_on_amazon=False, engine="v1": calls.append(
            (
                db,
                category,
                dry_run,
                strict_validation,
                sku_list,
                sku_file,
                only_not_on_amazon,
                engine,
            )
        ),
    )

    db = object()
    result = dispatch_task(
        db,
        "generate-listing-api",
        category="CABINET",
        dry_run=True,
        strict_validation=True,
        sku_list=["SKU1"],
        sku_file="/tmp/skus.txt",
        only_not_on_amazon=True,
        engine="shadow",
    )

    assert result is None
    assert calls == [
        (db, "CABINET", True, True, ["SKU1"], "/tmp/skus.txt", True, "shadow")
    ]


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


def test_dispatch_review_pending_attributes_passes_category(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_review_pending_attributes",
        lambda db, category=None, engine="v1", approve_human=False, sku=None: calls.append(
            (db, category, engine, approve_human, sku)
        ),
    )

    db = object()
    result = dispatch_task(
        db,
        "review-pending-attributes",
        category="CHAIR",
        approve_human=True,
        sku_list=["SKU1"],
    )

    assert result is None
    assert calls == [(db, "CHAIR", "v1", True, "SKU1")]


def test_dispatch_submit_reviewed_plans_passes_flags(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_submit_reviewed_plans",
        lambda db, category=None, dry_run=True, strict_validation=False, engine="v1": calls.append(
            (db, category, dry_run, strict_validation, engine)
        ),
    )

    db = object()
    result = dispatch_task(
        db,
        "submit-reviewed-plans",
        category="CHAIR",
        dry_run=False,
        strict_validation=True,
    )

    assert result is None
    assert calls == [(db, "CHAIR", False, True, "v1")]


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


def test_dispatch_amazon_order_daily_report_uses_cli_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_amazon_order_daily_report",
        lambda db, **kwargs: calls.append(db),
    )

    db = object()
    result = dispatch_task(db, "amazon-order-daily-report")

    assert result is None
    assert calls == [db]


def test_dispatch_sync_amazon_orders_uses_cli_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        task_dispatcher,
        "handle_sync_amazon_orders",
        lambda db, **kwargs: calls.append(db),
    )

    db = object()
    result = dispatch_task(db, "sync-amazon-orders")

    assert result is None
    assert calls == [db]


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
