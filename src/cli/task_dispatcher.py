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
    handle_confirm_listing_issue_repairs,
    handle_daily_check,
    handle_sync_amazon_orders,
    handle_amazon_order_daily_report,
    handle_analyze_listing_requirements_v2,
    handle_validate_listing_v2,
    handle_learn_required_from_submissions,
    handle_test_feishu_alert,
    handle_discover_product_type,
    handle_generate_details,
    handle_generate_attribute_rules,
    handle_generate_update_file,
    handle_import_amazon_report,
    handle_inventory_health,
    handle_keyword_research,
    handle_lifecycle_summary,
    handle_profit_analysis,
    handle_probe_variation_hierarchy,
    handle_repair_listing_issues,
    handle_review_pending_attributes,
    handle_suggest_category_mappings,
    handle_submit_reviewed_plans,
    handle_sync_amazon_report_api,
    handle_sync_confirmation_listing_issues,
    handle_sku_sync_from_csv,
    handle_confirm_price_inventory_api,
    handle_sync_listing_issues,
    handle_sync_inventory,
    handle_sync_prices,
    handle_sync_products,
    handle_update_listing_status,
    handle_delete_orphan_listings,
    handle_update_package_dimensions,
    handle_update_price_inventory_api,
    handle_update_prices,
    handle_auto_discover_category,
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
    strict_validation: bool = False,
    sku_list: Optional[list[str]] = None,
    sku_file: Optional[str] = None,
    only_not_on_amazon: bool = False,
):
    if return_listing_result and category:
        from src.services.product_listing_service import ProductListingService

        service = ProductListingService(db=db)
        return service.generate_listings_via_api(
            category_name=category,
            dry_run=True,
            validation_only=strict_validation,
            sku_list=sku_list,
            sku_file=sku_file,
            only_not_on_amazon=only_not_on_amazon,
        )
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
        strict_validation=kwargs.get("strict_validation", False),
        sku_list=kwargs.get("sku_list"),
        sku_file=kwargs.get("sku_file"),
        only_not_on_amazon=kwargs.get("only_not_on_amazon", False),
    ),
    "generate-listing-api": lambda db, **kwargs: handle_generate_listing_api(
        db,
        category=kwargs.get("category"),
        dry_run=kwargs.get("dry_run", True),
        strict_validation=kwargs.get("strict_validation", False),
        sku_list=kwargs.get("sku_list"),
        sku_file=kwargs.get("sku_file"),
        only_not_on_amazon=kwargs.get("only_not_on_amazon", False),
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
    "confirm-price-inventory-api": lambda db, **kwargs: handle_confirm_price_inventory_api(
        db
    ),
    "sync-listing-issues": lambda db, **kwargs: handle_sync_listing_issues(
        db, dry_run=kwargs.get("dry_run", True)
    ),
    "sync-confirmation-listing-issues": lambda db, **kwargs: (
        handle_sync_confirmation_listing_issues(db, dry_run=kwargs.get("dry_run", True))
    ),
    "repair-listing-issues": lambda db, **kwargs: handle_repair_listing_issues(
        db, dry_run=kwargs.get("dry_run", True)
    ),
    "confirm-listing-issue-repairs": lambda db, **kwargs: (
        handle_confirm_listing_issue_repairs(db)
    ),
    "review-pending-attributes": lambda db, **kwargs: handle_review_pending_attributes(
        db,
        category=kwargs.get("category"),
        engine=kwargs.get("engine", "v1"),
    ),
    "submit-reviewed-plans": lambda db, **kwargs: handle_submit_reviewed_plans(
        db,
        category=kwargs.get("category"),
        dry_run=kwargs.get("dry_run", True),
        strict_validation=kwargs.get("strict_validation", False),
        engine=kwargs.get("engine", "v1"),
    ),
    "update-package-dimensions": lambda db, **kwargs: handle_update_package_dimensions(
        db, dry_run=kwargs.get("dry_run", True)
    ),
    "delete-orphan-listings": lambda db, **kwargs: handle_delete_orphan_listings(
        db, dry_run=kwargs.get("dry_run", True)
    ),
    "sku-sync-from-csv": lambda db, **kwargs: handle_sku_sync_from_csv(db),
    "discover-product-type": lambda db, **kwargs: handle_discover_product_type(
        db, keywords=kwargs.get("category")
    ),
    "suggest-category-mappings": lambda db, **kwargs: handle_suggest_category_mappings(db),
    "auto-discover-category": lambda db, **kwargs: handle_auto_discover_category(
        db,
        category_code=kwargs.get("category_code"),
        all_unmapped=kwargs.get("all_unmapped", False),
        dry_run=kwargs.get("dry_run", True),
    ),
    "generate-attribute-rules": lambda db, **kwargs: handle_generate_attribute_rules(
        db,
        product_type=kwargs.get("product_type") or kwargs.get("category"),
    ),
    "analyze-listing-requirements-v2": lambda db, **kwargs: (
        handle_analyze_listing_requirements_v2(
            db,
            product_type=kwargs.get("product_type") or kwargs.get("category"),
            sku_list=kwargs.get("sku_list"),
        )
    ),
    "validate-listing-v2": lambda db, **kwargs: (
        handle_validate_listing_v2(
            db,
            product_type=kwargs.get("product_type") or kwargs.get("category"),
            sku_list=kwargs.get("sku_list"),
        )
    ),
    "learn-required-from-submissions": lambda db, **kwargs: (
        handle_learn_required_from_submissions(
            db,
            product_type=kwargs.get("product_type") or kwargs.get("category"),
        )
    ),
    "probe-variation-hierarchy": lambda db, **kwargs: handle_probe_variation_hierarchy(
        db,
        parent_sku=(kwargs.get("sku_list") or [kwargs.get("category") or ""])[0],
    ),
    "keyword-research": lambda db, **kwargs: handle_keyword_research(
        db,
        category=kwargs.get("category"),
        auto_confirm=kwargs.get("auto_confirm", False),
    ),
    "daily-check": lambda db, **kwargs: handle_daily_check(db),
    "sync-amazon-orders": lambda db, **kwargs: handle_sync_amazon_orders(db),
    "amazon-order-daily-report": lambda db, **kwargs: handle_amazon_order_daily_report(db),
    "test-feishu-alert": lambda db, **kwargs: handle_test_feishu_alert(db),
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
    strict_validation: bool = False,
    sku_list: Optional[list[str]] = None,
    sku_file: Optional[str] = None,
    only_not_on_amazon: bool = False,
    category_code: Optional[str] = None,
    all_unmapped: bool = False,
    product_type: Optional[str] = None,
    engine: str = "v1",
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
        strict_validation=strict_validation,
        sku_list=sku_list,
        sku_file=sku_file,
        only_not_on_amazon=only_not_on_amazon,
        category_code=category_code,
        all_unmapped=all_unmapped,
        product_type=product_type,
        engine=engine,
    )
