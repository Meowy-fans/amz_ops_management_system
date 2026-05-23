"""Task dispatching for CLI and programmatic entry points."""
from typing import Optional

from sqlalchemy.orm import Session

from src.cli.category_handlers import (
    handle_sync_giga_categories,
    handle_template_correction,
    handle_template_update,
    handle_update_mappings_from_csv,
)
from src.cli.listing_handlers import handle_generate_listing, handle_generate_listing_api
from src.cli.operation_handlers import (
    handle_competitive_analysis,
    handle_daily_check,
    handle_discover_product_type,
    handle_generate_details,
    handle_generate_update_file,
    handle_import_amazon_report,
    handle_inventory_health,
    handle_keyword_research,
    handle_lifecycle_summary,
    handle_profit_analysis,
    handle_suggest_category_mappings,
    handle_sync_amazon_report_api,
    handle_sku_sync_from_csv,
    handle_sync_listing_issues,
    handle_sync_inventory,
    handle_sync_prices,
    handle_sync_products,
    handle_update_listing_status,
    handle_update_price_inventory_api,
    handle_update_prices,
    handle_weekly_report,
)
from src.cli.query_handlers import (
    handle_list_categories,
    handle_pending_statistics,
    handle_recent_listings,
    handle_view_statistics,
)


class UnknownTaskError(ValueError):
    """Raised when a non-interactive task name is not registered."""


def _generate_listing_task(
    db: Session,
    category: Optional[str] = None,
    return_listing_result: bool = False,
):
    if return_listing_result and category:
        from src.services.product_listing_service import ProductListingService

        service = ProductListingService(db=db)
        return service.generate_listings_by_category(category)
    handle_generate_listing(db, category=category)
    return None


TASK_HANDLERS = {
    "sync-products": lambda db, **kwargs: handle_sync_products(
        db, auto_confirm=kwargs.get("auto_confirm", False)
    ),
    "import-amz-report": lambda db, **kwargs: handle_import_amazon_report(
        db, file_path=kwargs.get("file_path")
    ),
    "sync-amz-report-api": lambda db, **kwargs: handle_sync_amazon_report_api(db),
    "update-listing-status": lambda db, **kwargs: handle_update_listing_status(db),
    "generate-details": lambda db, **kwargs: handle_generate_details(db),
    "sync-prices": lambda db, **kwargs: handle_sync_prices(db),
    "sync-inventory": lambda db, **kwargs: handle_sync_inventory(db),
    "update-prices": lambda db, **kwargs: handle_update_prices(db),
    "generate-listing": lambda db, **kwargs: _generate_listing_task(
        db,
        category=kwargs.get("category"),
        return_listing_result=kwargs.get("return_listing_result", False),
    ),
    "generate-listing-api": lambda db, **kwargs: handle_generate_listing_api(
        db,
        category=kwargs.get("category"),
        dry_run=kwargs.get("dry_run", True),
    ),
    "view-statistics": lambda db, **kwargs: handle_view_statistics(db),
    "pending-statistics": lambda db, **kwargs: handle_pending_statistics(db),
    "recent-listings": lambda db, **kwargs: handle_recent_listings(db),
    "list-categories": lambda db, **kwargs: handle_list_categories(db),
    "template-update": lambda db, **kwargs: handle_template_update(
        db,
        template_path=kwargs.get("file_path"),
        category_name=kwargs.get("category"),
    ),
    "template-correction": lambda db, **kwargs: handle_template_correction(
        db,
        report_path=kwargs.get("file_path"),
        category_name=kwargs.get("category"),
    ),
    "sync-giga-categories": lambda db, **kwargs: handle_sync_giga_categories(
        db, auto_confirm=kwargs.get("auto_confirm", False)
    ),
    "update-mappings-from-csv": lambda db, **kwargs: handle_update_mappings_from_csv(
        db, csv_file_path=kwargs.get("file_path")
    ),
    "generate-update-file": lambda db, **kwargs: handle_generate_update_file(db),
    "update-price-inventory-api": lambda db, **kwargs: handle_update_price_inventory_api(
        db, dry_run=kwargs.get("dry_run", True)
    ),
    "sync-listing-issues": lambda db, **kwargs: handle_sync_listing_issues(
        db, dry_run=kwargs.get("dry_run", True)
    ),
    "sku-sync-from-csv": lambda db, **kwargs: handle_sku_sync_from_csv(db),
    "discover-product-type": lambda db, **kwargs: handle_discover_product_type(
        db, keywords=kwargs.get("category")
    ),
    "suggest-category-mappings": lambda db, **kwargs: handle_suggest_category_mappings(db),
    "keyword-research": lambda db, **kwargs: handle_keyword_research(
        db,
        category=kwargs.get("category"),
        auto_confirm=kwargs.get("auto_confirm", False),
    ),
    "daily-check": lambda db, **kwargs: handle_daily_check(db),
    "competitive-analysis": lambda db, **kwargs: handle_competitive_analysis(
        db,
        category=kwargs.get("category"),
        auto_confirm=kwargs.get("auto_confirm", False),
    ),
    "weekly-report": lambda db, **kwargs: handle_weekly_report(db),
    "profit-analysis": lambda db, **kwargs: handle_profit_analysis(db),
    "inventory-health": lambda db, **kwargs: handle_inventory_health(db),
    "lifecycle-summary": lambda db, **kwargs: handle_lifecycle_summary(db),
}


def dispatch_task(
    db: Session,
    task: str,
    category: Optional[str] = None,
    file_path: Optional[str] = None,
    auto_confirm: bool = False,
    return_listing_result: bool = False,
    dry_run: bool = True,
):
    """Dispatch a task while preserving existing task behavior."""
    t = task.strip().lower()
    handler = TASK_HANDLERS.get(t)
    if handler is None:
        raise UnknownTaskError(task)
    return handler(
        db,
        category=category,
        file_path=file_path,
        auto_confirm=auto_confirm,
        return_listing_result=return_listing_result,
        dry_run=dry_run,
    )
