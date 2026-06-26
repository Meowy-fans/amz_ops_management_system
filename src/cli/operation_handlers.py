"""CLI handlers for operational tasks."""
import logging
import os
import sys
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.services.amz_asin_family_parent_listing_status_manager import ListingStatusManager
from src.services.amz_full_list_importer_service import AmzFullListImporterService
from src.services.giga_inventory_sync_service import GigaInventorySyncService
from src.services.giga_price_sync_service import GigaPriceSyncService
from src.services.giga_sync_service import GigaSyncService
from src.services.pricing_service import PricingService
from src.services.product_detail_generation_service import ProductDetailGenerationService
from src.services.sku_mapping_service import SkuMappingService
from src.services.task_lock import PostgresAdvisoryLock

logger = logging.getLogger(__name__)


def handle_sync_products(db: Session, auto_confirm: bool = False):
    """1.1 同步全量Giga收藏商品详情"""
    logger.info("🚀 启动商品同步流程...")

    service = GigaSyncService(db)

    print("\n➡️  步骤 1/2: 获取收藏商品列表...")
    sku_list = service.get_full_sku_list()

    if not sku_list:
        print("✅ 没有收藏商品需要同步")
        return

    print(f"✅ 获取到 {len(sku_list)} 个收藏商品")

    if not auto_confirm:
        if sys.stdin and sys.stdin.isatty():
            confirm = input(f"⚠️  即将同步 {len(sku_list)} 个商品的详情，是否继续? (y/n): ").strip().lower()
            if confirm != "y":
                print("\n❌ 操作已取消")
                return
        else:
            print(f"⚠️  即将同步 {len(sku_list)} 个商品的详情")
            print("❌ 错误: 在 Web 界面运行此任务时，请务必勾选 '自动确认 (Auto Confirm)'")
            return

    print("\n➡️  步骤 2/2: 同步商品详情...")

    total, success, failed = service.sync_product_details(sku_list)

    print(f"\n{'=' * 60}")
    print("✅ 商品同步完成")
    print(f"{'=' * 60}")
    print(f"总计: {total}")
    print(f"成功: {success}")
    print(f"失败: {failed}")
    print(f"{'=' * 60}\n")


def handle_import_amazon_report(db: Session, file_path: Optional[str] = None):
    """1.2 导入亚马逊全量listing数据"""
    logger.info("🚀 启动Amazon数据导入流程...")

    if not file_path:
        file_path = input("\n请输入Amazon报告文件路径(.txt): ").strip().strip('"')

    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return

    service = AmzFullListImporterService(db)
    service.import_report_from_file(file_path)


def handle_sync_amazon_report_api(db: Session):
    """1.2 API 同步亚马逊全量 listing 数据"""
    logger.info("🚀 启动 Amazon Reports API 数据同步流程...")
    print("\n" + "=" * 70)
    print("📦 API 同步亚马逊全量 listing 数据")
    print("=" * 70)

    service = AmzFullListImporterService(db)
    service.sync_report_from_api()


def handle_update_listing_status(db: Session):
    """1.3 更新亚马逊父品发品状态"""
    logger.info("🚀 启动发品日志状态更新流程...")
    print("\n" + "=" * 70)
    print("📦 更新亚马逊父品发品状态")
    print("=" * 70)

    try:
        manager = ListingStatusManager(db=db)
        manager.update_statuses_to_listed()
        print("=" * 70)
    except Exception as e:
        print(f"\n❌ 执行发品状态更新时发生错误: {e}")
        logging.exception("详细错误:")


def handle_generate_details(db: Session):
    """1.4 使用AI生成商品详情"""
    logger.info("🚀 启动AI详情生成流程...")

    llm_provider = os.getenv("LLM_PROVIDER", "deepseek").upper()
    print(f"\n🤖 使用 {llm_provider} 模型（从环境变量读取）")

    service = ProductDetailGenerationService(db=db)
    service.process_all_skus()

    print("\n➡️  自动触发SKU映射...")
    mapping_service = SkuMappingService(db)
    total, created = mapping_service.sync_mappings_from_llm_details()
    print(f"✅ SKU映射完成。检查: {total}, 新建: {created}")


def handle_sync_prices(db: Session):
    """1.5 同步Giga商品价格"""
    logger.info("🚀 启动价格同步流程...")

    service = GigaPriceSyncService(db)
    result = service.sync_all_prices()

    logger.info(f"价格同步完成: {result}")


def handle_sync_inventory(db: Session):
    """1.6 同步Giga商品库存"""
    logger.info("🚀 启动库存同步流程...")

    service = GigaInventorySyncService(db)
    result = service.sync_all_inventory()

    logger.info(f"库存同步完成: {result}")


def handle_update_prices(db: Session):
    """1.7 更新售价"""
    logger.info("🚀 启动价格更新流程...")

    service = PricingService(db)
    total, success, report_data = service.update_prices()

    if report_data and len(report_data) > 0:
        print("\n📊 价格更新样例（前5条）:")
        print("-" * 100)
        for i, row in enumerate(report_data[:5], 1):
            print(f"{i}. {row['meow_sku']:20} | 品类: {row['category']:15} | "
                  f"成本: ${row['total_cost']:8} | 售价: ${row['final_price']:8} | "
                  f"毛利: {row['margin']}")

        if len(report_data) > 5:
            print(f"... 还有 {len(report_data) - 5} 条记录")
        print("-" * 100)


def handle_sku_sync_from_csv(db: Session):
    """4.1 从CSV批量同步SKU映射"""
    print("\n" + "=" * 70)
    print("📦 从CSV批量同步SKU映射")
    print("=" * 70)
    print("\n⚠️  此功能暂未实现，请等待后续版本。")
    print("=" * 70)


def handle_generate_update_file(db: Session):
    """5.1 (一键) 生成亚马逊价格与库存更新文件"""
    from src.services.amz_inventory_price_updater_service import InventoryPriceUpdaterService

    logger.info("🚀 启动生成亚马逊库存价格更新文件流程...")
    print("\n" + "=" * 70)
    print("📦 (一键) 生成亚马逊价格与库存更新文件")
    print("=" * 70)

    try:
        service = InventoryPriceUpdaterService(db=db)
        service.generate_update_file()
    except Exception as e:
        print(f"\n❌ 生成更新文件时发生错误: {e}")
        logging.exception("详细错误:")


def handle_update_price_inventory_api(db: Session, dry_run: bool = True):
    """5.2 通过 Amazon SP-API 更新价格和库存 (patchListingsItem)"""
    from src.services.amz_inventory_price_updater_service import InventoryPriceUpdaterService

    logger.info("Starting Amazon SP-API price/inventory update (dry_run=%s)", dry_run)
    print("\n" + "=" * 70)
    mode_label = "DRY RUN (preview)" if dry_run else "LIVE (real submission)"
    print(f"Amazon SP-API Price & Quantity Update - {mode_label}")
    print("=" * 70)

    lock = PostgresAdvisoryLock(db, "amazon_price_inventory_update")
    if not lock.acquire():
        print("Another price/inventory update is already running; skipping this run.")
        logger.warning("Skipped price/inventory update because advisory lock is held")
        return

    try:
        service = InventoryPriceUpdaterService(db=db)
        results = service.submit_updates_via_api(dry_run=dry_run)
        if results:
            print(f"\nProcessed {len(results)} SKUs.")
    except Exception as e:
        print(f"\nPrice/inventory API update failed: {e}")
        logging.exception("Detailed error:")
        raise
    finally:
        lock.release()


def handle_confirm_price_inventory_api(db: Session):
    """5.2b 延迟确认 Amazon SP-API 价格和库存更新结果"""
    from src.services.amazon_price_inventory_delayed_confirmation_service import (
        AmazonPriceInventoryDelayedConfirmationService,
    )

    logger.info("Starting delayed Amazon SP-API price/inventory confirmation")
    print("\n" + "=" * 70)
    print("Amazon SP-API Price & Quantity Delayed Confirmation")
    print("=" * 70)

    lock = PostgresAdvisoryLock(db, "amazon_price_inventory_update")
    if not lock.acquire():
        print("Another price/inventory update is already running; skipping confirmation.")
        logger.warning("Skipped delayed confirmation because advisory lock is held")
        return

    try:
        minutes = int(os.getenv("PRICE_INVENTORY_CONFIRM_AFTER_MINUTES", "30"))
        limit = int(os.getenv("PRICE_INVENTORY_CONFIRM_LIMIT", "500"))
        service = AmazonPriceInventoryDelayedConfirmationService(db=db)
        results = service.confirm_pending(older_than_minutes=minutes, limit=limit)
        if results:
            print(f"\nConfirmed {len(results)} prior submissions.")
    except Exception as e:
        print(f"\nPrice/inventory delayed confirmation failed: {e}")
        logging.exception("Detailed error:")
        raise
    finally:
        lock.release()


def handle_sync_listing_issues(db: Session, dry_run: bool = True):
    """5.3 同步 Amazon listing issues 并启动修复流程"""
    from src.services.amazon_listing_issue_sync_service import (
        AmazonListingIssueSyncService,
    )

    logger.info("Starting Amazon listing issue sync (dry_run=%s)", dry_run)
    print("\n" + "=" * 70)
    mode_label = "DRY RUN (plan repairs)" if dry_run else "LIVE (submit safe patches)"
    print(f"Amazon Listing Issue Sync - {mode_label}")
    print("=" * 70)

    limit_text = os.getenv("LISTING_ISSUE_SYNC_LIMIT")
    limit = int(limit_text) if limit_text else None
    include_report = os.getenv("LISTING_ISSUE_INCLUDE_SUPPRESSED_REPORT", "true").lower()

    try:
        service = AmazonListingIssueSyncService(db=db)
        service.sync_and_repair(
            limit=limit,
            dry_run=dry_run,
            include_suppressed_report=include_report not in {"0", "false", "no"},
        )
    except Exception as e:
        print(f"\nListing issue sync failed: {e}")
        logging.exception("Detailed error:")


def handle_sync_confirmation_listing_issues(db: Session, dry_run: bool = True):
    """同步价格/库存 confirmation 中发现的 Amazon listing issues"""
    from src.services.amazon_listing_issue_sync_service import (
        AmazonListingIssueSyncService,
    )

    logger.info("Starting confirmation listing issue sync (dry_run=%s)", dry_run)
    print("\n" + "=" * 70)
    mode_label = "DRY RUN (plan repairs)" if dry_run else "LIVE (submit safe patches)"
    print(f"Confirmation Listing Issue Sync - {mode_label}")
    print("=" * 70)

    limit = int(os.getenv("CONFIRMATION_LISTING_ISSUE_SYNC_LIMIT", "500"))
    try:
        service = AmazonListingIssueSyncService(db=db)
        service.sync_confirmation_issues(limit=limit, dry_run=dry_run)
    except Exception as e:
        print(f"\nConfirmation listing issue sync failed: {e}")
        logging.exception("Detailed error:")
        raise


def handle_repair_listing_issues(db: Session, dry_run: bool = True):
    """执行 open Amazon listing issues 的安全自动修复计划"""
    from src.services.amazon_listing_issue_repair_service import (
        AmazonListingIssueRepairService,
    )

    logger.info("Starting listing issue repair (dry_run=%s)", dry_run)
    print("\n" + "=" * 70)
    mode_label = "DRY RUN" if dry_run else "LIVE"
    print(f"Amazon Listing Issue Repair - {mode_label}")
    print("=" * 70)

    source = os.getenv(
        "LISTING_ISSUE_REPAIR_SOURCE",
        "price_inventory_confirmation",
    )
    limit_text = os.getenv("LISTING_ISSUE_REPAIR_LIMIT")
    limit = int(limit_text) if limit_text else None
    try:
        service = AmazonListingIssueRepairService(db=db)
        service.repair_open_issues(source=source, limit=limit, dry_run=dry_run)
    except Exception as e:
        print(f"\nListing issue repair failed: {e}")
        logging.exception("Detailed error:")
        raise


def handle_confirm_listing_issue_repairs(db: Session):
    """延迟确认已提交的 Amazon listing issue 修复动作"""
    from src.services.amazon_listing_issue_repair_service import (
        AmazonListingIssueRepairService,
    )

    print("\n" + "=" * 70)
    print("Amazon Listing Issue Repair Confirmation")
    print("=" * 70)

    minutes = int(os.getenv("LISTING_ISSUE_REPAIR_CONFIRM_AFTER_MINUTES", "30"))
    limit = int(os.getenv("LISTING_ISSUE_REPAIR_CONFIRM_LIMIT", "100"))
    try:
        service = AmazonListingIssueRepairService(db=db)
        service.confirm_submitted_repairs(
            older_than_minutes=minutes,
            limit=limit,
        )
    except Exception as e:
        print(f"\nListing issue repair confirmation failed: {e}")
        logging.exception("Detailed error:")
        raise


def handle_review_pending_attributes(
    db: Session,
    category: Optional[str] = None,
    engine: str = "v1",
):
    """Review pending required LLM attributes."""
    print("\n" + "=" * 70)
    print(f"Amazon Listing Pending Attribute Review (engine={engine})")
    print("=" * 70)
    if not category:
        print("缺少 --category；请指定需要审核的 Amazon product type。")
        return {"success": False, "message": "category_required"}

    limit = int(os.getenv("ATTRIBUTE_REVIEW_LIMIT", "50"))
    if engine == "v2":
        from src.services.review_adapter_v2 import ReviewAdapterV2

        result = ReviewAdapterV2(db=db).review_pending_paths(
            category=category,
            limit=limit,
        )
        print(
            f"Reviewed rows={result['rows']} reviewed={result['reviewed']} "
            f"human_required={result['human_required']}"
        )
        return {"success": True, **result}

    from src.services.review_manager import ReviewManager

    result = ReviewManager(db=db).review_pending_attributes(
        category=category,
        limit=limit,
    )
    print(
        f"Reviewed rows={result['rows']} reviewed={result['reviewed']} "
        f"completed={result['completed']} human_required={result['human_required']}"
    )
    return {"success": True, **result}


def handle_submit_reviewed_plans(
    db: Session,
    category: Optional[str] = None,
    dry_run: bool = True,
    strict_validation: bool = False,
    engine: str = "v1",
):
    """Submit completed pending-review listing plans."""
    print("\n" + "=" * 70)
    mode_label = (
        "STRICT DRY RUN (Amazon VALIDATION_PREVIEW)"
        if strict_validation
        else "DRY RUN" if dry_run else "LIVE"
    )
    print(f"Amazon Listing Reviewed Plan Submission - {mode_label} (engine={engine})")
    print("=" * 70)
    if not category:
        print("缺少 --category；请指定需要提交的 Amazon product type。")
        return {"success": False, "message": "category_required", "results": []}

    limit = int(os.getenv("ATTRIBUTE_REVIEW_SUBMIT_LIMIT", "50"))
    if engine == "v2":
        from src.services.review_adapter_v2 import ReviewAdapterV2

        results = ReviewAdapterV2(db=db).submit_reviewed_paths(
            category=category,
            dry_run=dry_run,
            limit=limit,
        )
        print(f"Submitted reviewed V2 plans: {len(results)}")
        for item in results[:5]:
            print(f"  {item.get('sku')}: {item.get('status')}")
        return {"success": True, "results": results}

    from src.services.review_manager import ReviewManager

    results = ReviewManager(db=db).submit_reviewed_plans(
        category=category,
        dry_run=dry_run,
        validation_only=strict_validation,
        limit=limit,
    )
    print(f"Submitted reviewed plans: {len(results)}")
    for item in results[:5]:
        print(f"  {item.get('sku')}: {item.get('status')}")
    return {"success": True, "results": results}


def handle_discover_product_type(db: Session, keywords: Optional[str] = None):
    """6.1 通过 Amazon Product Type Definitions API 搜索品类"""
    print("\n" + "=" * 70)
    print("Amazon Product Type Discovery")
    print("=" * 70)

    if not keywords:
        keywords = input("\nEnter search keywords (e.g. 'bathroom vanity'): ").strip()
    if not keywords:
        print("No keywords provided.")
        return

    print(f"\nSearching Amazon product types for: {keywords}")

    from infrastructure.amazon.product_type_client import AmazonProductTypeClient
    from src.services.amazon_schema_service import AmazonSchemaService

    client = AmazonProductTypeClient()
    schema_svc = AmazonSchemaService(db)

    try:
        types = client.search_product_types(keywords)
    except Exception as e:
        print(f"Search failed: {e}")
        return

    if not types:
        print("No matching product types found.")
        return

    print(f"\nFound {len(types)} candidate(s):\n")
    for i, pt in enumerate(types, 1):
        print(f"  [{i}] {pt}")
        try:
            required = schema_svc.get_required_properties(pt)
            if required:
                print(f"      Required fields ({len(required)}): {', '.join(required[:15])}")
                if len(required) > 15:
                    print(f"      ... and {len(required) - 15} more")
        except Exception:
            print("      (could not fetch requirements)")

    print("\n  [0] Cancel")
    choice = input("\nSelect product type to cache schema and set as mapping target: ").strip()
    if choice == "0" or not choice:
        return

    try:
        idx = int(choice) - 1
        selected = types[idx]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return

    # Cache the schema
    print(f"\nFetching and caching schema for {selected}...")
    try:
        schema_svc.fetch_and_cache(selected)
        print(f"Schema cached ({len(schema_svc.get_required_properties(selected))} required props)")
    except Exception as e:
        print(f"Schema fetch failed: {e}")
        return

    # Optionally write category mapping
    print(f"\nProduct type '{selected}' is ready.")
    map_choice = input("Write this to supplier_categories_map? (y/n): ").strip().lower()
    if map_choice == "y":
        code = input("Enter supplier_category_code (e.g. '10143'): ").strip()
        platform = input("Enter supplier_platform [giga]: ").strip() or "giga"
        if code:
            db.execute(
                __import__("sqlalchemy").text(
                    "UPDATE supplier_categories_map SET standard_category_name = :name "
                    "WHERE supplier_platform = :plat AND supplier_category_code = :code "
                    "AND standard_category_name = ''"
                ),
                {"name": selected, "plat": platform, "code": code},
            )
            db.commit()
            print(f"Updated: {platform}/{code} -> {selected}")


def handle_suggest_category_mappings(db: Session):
    """6.2 为未映射的 Giga 品类自动建议 Amazon product type"""
    print("\n" + "=" * 70)
    print("Auto-Suggest Category Mappings")
    print("=" * 70)

    from sqlalchemy import text

    # Find unmapped categories with sample products
    rows = db.execute(text("""
        SELECT DISTINCT
            scm.supplier_category_code,
            scm.supplier_category_name,
            psr.raw_data->>'name' AS sample_name
        FROM supplier_categories_map scm
        JOIN giga_product_sync_records psr
            ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
        WHERE scm.standard_category_name = ''
          AND scm.supplier_platform = 'giga'
        LIMIT 3
    """)).fetchall()

    if not rows:
        print("No unmapped categories found.")
        return

    from infrastructure.amazon.product_type_client import AmazonProductTypeClient

    client = AmazonProductTypeClient()

    for row in rows:
        code = row[0]
        cat_name = row[1] or code
        sample = row[2] or cat_name

        # Use first 3 words as search keywords
        keywords = " ".join(str(sample).split()[:5])
        print(f"\n--- {code} ({cat_name}) ---")
        print(f"  Sample: {sample[:80]}...")
        print(f"  Searching with: {keywords}")

        try:
            types = client.search_product_types(keywords)
            if types:
                print(f"  Candidates: {', '.join(types[:5])}")
            else:
                print("  No matches found")
        except Exception as e:
            print(f"  Search failed: {e}")

    print("\nUse 'discover-product-type' to explore and set specific mappings.")


def handle_auto_discover_category(
    db: Session,
    category_code: Optional[str] = None,
    all_unmapped: bool = False,
    dry_run: bool = True,
):
    """Automatically infer Amazon product type mappings from Catalog Items."""
    from src.services.auto_category_mapper import AutoCategoryMapper

    print("\n" + "=" * 70)
    print("Auto Category Mapping")
    print("=" * 70)
    print(f"Mode: {'DRY RUN' if dry_run else 'WRITE'}")

    if not all_unmapped and not category_code:
        print("Please provide --category-code or --all-unmapped.")
        return

    mapper = AutoCategoryMapper(db)
    if all_unmapped:
        results = mapper.discover_unmapped(dry_run=dry_run)
    else:
        results = [mapper.discover_category(str(category_code), dry_run=dry_run)]

    if not results:
        print("No categories to process.")
        return

    for result in results:
        _print_auto_category_mapping_result(result)

    counts: Dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    print("\nSummary:")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")


def _print_auto_category_mapping_result(result: Any) -> None:
    print("\n" + "-" * 70)
    print(f"Category: {result.category_code} ({result.category_name})")
    print(f"Status: {result.status}")
    if result.selected_product_type:
        print(
            "Selected product type: "
            f"{result.selected_product_type} (confidence={result.confidence:.2f})"
        )
    if result.vote_counts:
        votes = ", ".join(
            f"{name}={count}" for name, count in result.vote_counts.items()
        )
        print(f"Catalog votes: {votes}")
    if result.fallback_candidates:
        print(f"Fallback candidates: {', '.join(result.fallback_candidates[:5])}")
    if result.asins:
        print(f"ASINs: {', '.join(result.asins[:10])}")
    if result.warnings:
        for warning in result.warnings:
            print(f"Warning: {warning}")
    print(f"Written: {result.written}")
    print(f"Schema cached: {result.schema_cached}")


def handle_generate_attribute_rules(
    db: Session,
    product_type: Optional[str] = None,
):
    """Generate draft API attribute rules from cached Product Type schema."""
    from src.services.amazon_schema_service import AmazonSchemaService
    from src.services.attribute_rule_generator import AttributeRuleGenerator

    print("\n" + "=" * 70)
    print("Generate API Attribute Rules Draft")
    print("=" * 70)
    if not product_type:
        product_type = input("\nEnter Amazon product type (e.g. SOFA): ").strip()
    if not product_type:
        print("No product type provided.")
        return None

    generator = AttributeRuleGenerator(schema_service=AmazonSchemaService(db))
    result = generator.generate(product_type=product_type, write=True, overwrite=False)

    print(f"\nProduct type: {result.product_type}")
    print(f"Rule file: {result.path}")
    print(f"Written: {result.written}")
    print(f"Already existed: {result.existed}")
    print(f"Required attributes: {result.required_count}")
    print(f"Generated attributes: {result.generated_attribute_count}")
    print(f"Manual review items: {result.manual_review_count}")
    print(f"Mode: {result.rules.get('mode')}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return result.as_dict()


def handle_probe_variation_hierarchy(
    db: Session,
    parent_sku: Optional[str] = None,
):
    """Read-only probe for an online variation parent hierarchy."""
    if not parent_sku:
        parent_sku = input("\nEnter parent SKU: ").strip()
    if not parent_sku:
        print("No parent SKU provided.")
        return None

    from infrastructure.amazon.catalog_client import AmazonCatalogClient
    from infrastructure.amazon.listings_client import AmazonListingsClient
    from src.services.variation_hierarchy_probe import VariationHierarchyProbe

    print("\n" + "=" * 70)
    print("Variation Hierarchy Probe - READ ONLY")
    print("=" * 70)
    print(f"Parent SKU: {parent_sku}")

    probe = VariationHierarchyProbe(
        listings_client=AmazonListingsClient(),
        catalog_client=AmazonCatalogClient(),
    )
    result = probe.probe_parent(parent_sku)
    print(f"Status: {result.probe_status}")
    print(f"Parent ASIN: {result.parent_asin or 'N/A'}")
    print(f"Child ASINs: {len(result.child_asins)}")
    if result.child_asins:
        print(f"  {', '.join(result.child_asins[:10])}")
    print(f"Online sibling facts: {len(result.online_sibling_facts)}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return result.as_dict()


def handle_keyword_research(
    db: Session, category: Optional[str] = None, auto_confirm: bool = False
):
    """Run keyword research for pending products in a category."""
    from src.services.keyword_research_service import KeywordResearchService
    from src.repositories.product_data_repository import ProductDataRepository
    from src.repositories.product_listing_repository import ProductListingRepository
    from src.services.product_normalizer import GigaProductNormalizer

    if not category:
        print("Please specify --category (e.g. CABINET, HOME_MIRROR)")
        return

    listing_repo = ProductListingRepository(db)
    product_repo = ProductDataRepository(db)

    all_pending = listing_repo.get_pending_listing_skus()
    if not all_pending:
        print("No pending products found.")
        return

    print(f"\n{'='*60}")
    print(f"Keyword Research — {category}")
    print(f"Scanning {len(all_pending)} pending SKUs...")
    print(f"{'='*60}\n")

    service = KeywordResearchService()
    normalizer = GigaProductNormalizer()

    count = 0
    for meow_sku in all_pending:
        raw_data = product_repo.get_full_product_data(meow_sku)
        if not raw_data:
            continue

        try:
            product = normalizer.normalize(raw_data)
        except Exception:
            continue

        count += 1
        print(f"  [{count}] {meow_sku}: {product.name[:60]}...")
        result = service.research(product, product_type=category, category=category)

        if result.core_keywords:
            print(f"    Core: {', '.join(result.core_keywords[:5])}")
            print(f"    Long-tail: {', '.join(result.long_tail_keywords[:5])}")
            print(f"    Search Terms: {result.backend_search_terms[:80]}...")
            print(f"    Target: {result.target_audience} | Use: {result.intended_use}")
            print(f"    Room: {result.room_type} | Style: {result.style}")
        if result.warnings:
            print(f"    Warnings: {result.warnings}")
        print()

    print(f"Keyword research complete for {count} products.")


def _resolve_sku_to_asin(db: Session, meow_skus: List[str]) -> Dict[str, str]:
    """Resolve meow_sku → ASIN from amz_all_listing_report."""
    from sqlalchemy import text

    if not meow_skus:
        return {}
    rows = db.execute(
        text("""
            SELECT "seller-sku", asin1 FROM amz_all_listing_report
            WHERE "seller-sku" = ANY(:skus) AND asin1 IS NOT NULL AND asin1 != ''
        """),
        {"skus": meow_skus},
    ).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


def _resolve_meow_to_giga(db: Session, meow_skus: List[str]) -> Dict[str, str]:
    """Resolve meow_sku → giga_sku via meow_sku_map."""
    from sqlalchemy import text

    if not meow_skus:
        return {}
    rows = db.execute(
        text("SELECT meow_sku, vendor_sku FROM meow_sku_map WHERE meow_sku = ANY(:skus)"),
        {"skus": meow_skus},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _resolve_giga_to_name(db: Session, giga_skus: List[str]) -> Dict[str, str]:
    """Resolve giga_sku → product name from giga_product_sync_records."""
    from sqlalchemy import text

    if not giga_skus:
        return {}
    rows = db.execute(
        text("""
            SELECT giga_sku, raw_data->>'name' AS name
            FROM giga_product_sync_records
            WHERE giga_sku = ANY(:skus)
        """),
        {"skus": giga_skus},
    ).fetchall()
    return {r[0]: (r[1] or "") for r in rows}


def _resolve_giga_to_cost(db: Session, giga_skus: List[str]) -> Dict[str, Dict[str, float]]:
    """Resolve giga_sku → {base_price, shipping_fee} from giga_product_base_prices."""
    from sqlalchemy import text

    if not giga_skus:
        return {}
    rows = db.execute(
        text("""
            SELECT DISTINCT ON (giga_sku)
                giga_sku, base_price, shipping_fee
            FROM giga_product_base_prices
            WHERE giga_sku = ANY(:skus) AND sku_available = TRUE
            ORDER BY giga_sku, updated_at DESC
        """),
        {"skus": giga_skus},
    ).fetchall()
    return {
        r[0]: {
            "base_price": float(r[1]) if r[1] else 0.0,
            "shipping_fee": float(r[2]) if r[2] else 0.0,
        }
        for r in rows
    }


def _resolve_meow_to_price(db: Session, meow_skus: List[str]) -> Dict[str, float]:
    """Resolve meow_sku → selling price from amz_all_listing_report."""
    from sqlalchemy import text

    if not meow_skus:
        return {}
    rows = db.execute(
        text("""
            SELECT "seller-sku", price FROM amz_all_listing_report
            WHERE "seller-sku" = ANY(:skus) AND price IS NOT NULL AND price > 0
        """),
        {"skus": meow_skus},
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1]}


def _resolve_giga_to_inventory(db: Session, giga_skus: List[str]) -> List[Dict[str, Any]]:
    """Get inventory items from giga_inventory table."""
    from sqlalchemy import text

    if not giga_skus:
        return []
    rows = db.execute(
        text("""
            SELECT giga_sku, quantity, next_arrival_date, next_arrival_qty
            FROM giga_inventory
            WHERE giga_sku = ANY(:skus)
        """),
        {"skus": giga_skus},
    ).fetchall()
    return [
        {
            "giga_sku": r[0],
            "quantity": int(r[1]) if r[1] else 0,
            "next_arrival_date": str(r[2]) if r[2] and str(r[2]) != "1970-01-01" else "",
            "next_arrival_qty": int(r[3]) if r[3] else 0,
        }
        for r in rows
    ]


def _get_active_listings(db: Session) -> List[Dict[str, Any]]:
    """Get all active listings from amz_all_listing_report."""
    from sqlalchemy import text

    rows = db.execute(
        text("""
            SELECT "seller-sku", asin1, "item-name", price, status, "open-date"
            FROM amz_all_listing_report
            WHERE asin1 IS NOT NULL AND asin1 != ''
            ORDER BY "open-date" DESC NULLS LAST
        """)
    ).fetchall()
    return [
        {
            "sku": r[0] or "",
            "asin": r[1] or "",
            "name": r[2] or "",
            "price": float(r[3]) if r[3] else 0.0,
            "status": r[4] or "",
            "open_date": str(r[5]) if r[5] else "",
        }
        for r in rows
    ]


# ══════════════════════════════════════════════════════════════════════
# Phase 1-3 Handlers (real data)
# ══════════════════════════════════════════════════════════════════════


def handle_competitive_analysis(
    db: Session, category: Optional[str] = None, auto_confirm: bool = False
):
    """Run competitive landscape analysis — keyword-based competitor discovery.

    Flow:
      1. Get our active ASINs from database
      2. For each product, search keywords → discover competitor ASINs
      3. Pull each competitor's price + BSR
      4. Compute competitiveness score + pricing recommendation
    """
    from src.services.competitive_intel_service import CompetitiveIntelService

    if not category:
        print("Please specify --category (e.g. CABINET)")
        return

    active = _get_active_listings(db)
    if not active:
        print("No active listings found. Run 'import-amz-report' first.")
        return

    # Category → search keyword mapping
    CATEGORY_KEYWORDS = {
        "CABINET": ["bathroom vanity", "bathroom cabinet with sink"],
        "HOME_MIRROR": ["LED bathroom mirror", "wall mounted vanity mirror"],
        "BATHTUB_SHOWER_TRIM_KIT": ["bathtub shower trim kit", "shower faucet set"],
    }
    keywords = CATEGORY_KEYWORDS.get(category.upper(), [category.lower().replace("_", " ")])

    print(f"\n{'='*60}")
    print(f"Competitive Analysis — {category}")
    print(f"Search keywords: {keywords}")
    print(f"Active products: {len(active)}")
    print(f"{'='*60}\n")

    service = CompetitiveIntelService()

    # Get costs + SKU mappings
    meow_skus = [item["sku"] for item in active if item["sku"]]
    meow_to_giga = _resolve_meow_to_giga(db, meow_skus)
    giga_skus = list(set(meow_to_giga.values()))
    giga_to_cost = _resolve_giga_to_cost(db, giga_skus)

    count = 0
    limit = min(len(active), 5)  # Per-product keyword search + pricing calls
    for item in active[:limit]:
        sku = item["sku"]
        asin = item["asin"]
        our_price = item["price"]
        giga_sku = meow_to_giga.get(sku, "")
        cost_data = giga_to_cost.get(giga_sku, {})
        landed_cost = cost_data.get("base_price", 0) + cost_data.get("shipping_fee", 0)

        count += 1
        name = (item["name"] or sku)[:50]
        print(f"  [{count}] {name}")
        print(f"      ASIN: {asin}  Our Price: ${our_price:.2f}" if our_price else f"      ASIN: {asin}")
        print(f"      Landed Cost: ${landed_cost:.2f}" if landed_cost else "      Landed Cost: N/A")
        print(f"      Searching keywords: {keywords}")

        landscape = service.analyze_by_keywords(
            keywords=keywords,
            target_asin=asin,
            target_sku=sku,
            target_price=our_price if our_price > 0 else None,
            target_cost=landed_cost if landed_cost > 0 else None,
            max_competitors=8,
        )

        print(f"      Competitors found: {len(landscape.competitors)}")
        for c in landscape.competitors[:5]:
            bsr_str = f"BSR=#{c.bsr}" if c.bsr else ""
            price_str = f"${c.lowest_fba_price:.2f}" if c.lowest_fba_price else "N/A"
            print(f"        {c.asin}: {c.title[:50]}")
            print(f"          Brand={c.brand}  Price={price_str}  {bsr_str}  Sellers={c.offer_count}")

        print(f"      Score: {landscape.competitiveness_score:.0f}/100 → {landscape.competitive_label}")
        print(f"      Median BSR: {landscape.median_bsr or 'N/A'}")
        if landscape.suggested_price and landscape.target_price:
            print(f"      Suggested Price: ${landscape.suggested_price:.2f} (vs our ${landscape.target_price:.2f})")
            print(f"      Est. Margin: {landscape.estimated_margin_at_suggested or 0:.1%}")
        for alert in landscape.alerts:
            print(f"      ⚠️  {alert}")
        print()

    print(f"Competitive analysis complete for {count} products.")


def handle_weekly_report(db: Session, **kwargs):
    """Generate and send the weekly operations report using real data."""
    from src.services.weekly_report_service import WeeklyReportService
    from src.services.daily_check_service import DailyCheckService
    from infrastructure.feishu_client import FeishuClient

    print("\nGenerating weekly report...\n")

    # Collect daily check summary
    daily = DailyCheckService(db)
    daily.run()

    # Collect listing issue stats from the database
    listing_issue_summary = {"open_issues": 0, "resolved_this_week": 0, "new_this_week": 0}
    try:
        from sqlalchemy import text
        open_row = db.execute(
            text("SELECT COUNT(*) FROM amazon_listing_issues WHERE status = 'open'")
        ).fetchone()
        listing_issue_summary["open_issues"] = open_row[0] if open_row else 0
    except Exception:
        pass

    # Get active listings for competitive context
    active = _get_active_listings(db)
    active_count = len(active)

    # Build report
    report_service = WeeklyReportService()
    report = report_service.generate(
        ranking_data={
            "total_tracked": 0,
            "improved_count": 0,
            "declined_count": 0,
            "new_count": 0,
            "lost_count": 0,
        },
        competitive_data={
            "total_monitored": active_count,
            "price_alerts": [],
            "new_entrants": 0,
            "score_distribution": {},
        },
        listing_issue_summary=listing_issue_summary,
    )

    # Display in console
    print(f"Week: {report.week_start} → {report.week_end}")
    print(f"Active Listings: {active_count}")
    print(f"Overall Status: {report.overall_status}")
    print()
    print("Top Actions:")
    for i, action in enumerate(report.top_actions, 1):
        print(f"  {i}. {action}")
    print()

    for sec in report.sections:
        print(f"[{sec.status}] {sec.title}")
        print(f"  {sec.summary}")
        for detail in sec.details[:3]:
            print(f"    • {detail}")
        print()

    # Push to Feishu
    feishu = FeishuClient.from_env()
    sections = report_service.to_feishu_sections(report)
    feishu.send_weekly_report(
        title=f"亚马逊运营周报 — {report.week_start}~{report.week_end}",
        sections=sections,
    )
    print("Weekly report pushed to Feishu.")


def handle_profit_analysis(db: Session, **kwargs):
    """Run per-unit profit analysis using real cost and pricing data."""
    from src.services.profit_analyzer import ProfitAnalyzer
    from src.repositories.product_listing_repository import ProductListingRepository

    print("\nProfit Analysis Report\n" + "=" * 60)

    analyzer = ProfitAnalyzer()
    listing_repo = ProductListingRepository(db)

    all_skus = listing_repo.get_pending_listing_skus()
    active = _get_active_listings(db)

    # Merge: pending + active, deduplicated
    all_skus_set = set(all_skus)
    for item in active:
        sku = item["sku"]
        if sku:
            all_skus_set.add(sku)
    all_skus = list(all_skus_set)

    if not all_skus:
        print("No products found. Import listing data first.")
        return

    print(f"Analyzing {len(all_skus)} products...\n")

    # Real data chains
    meow_to_giga = _resolve_meow_to_giga(db, all_skus)
    giga_skus = list(set(meow_to_giga.values()))
    giga_to_cost = _resolve_giga_to_cost(db, giga_skus)
    sku_to_price = _resolve_meow_to_price(db, all_skus)
    giga_to_name = _resolve_giga_to_name(db, giga_skus)

    sku_data = []
    for sku in all_skus:
        giga_sku = meow_to_giga.get(sku, sku)
        cost_data = giga_to_cost.get(giga_sku, {})
        landed_cost = cost_data.get("base_price", 0) + cost_data.get("shipping_fee", 0)
        selling_price = sku_to_price.get(sku, 0.0)
        product_name = giga_to_name.get(giga_sku, "")

        if landed_cost <= 0 and selling_price <= 0:
            continue  # no meaningful data

        sku_data.append({
            "sku": sku,
            "asin": "",
            "product_name": product_name,
            "selling_price": selling_price or 0.0,
            "units_sold": 0,  # requires Orders API for real data
            "landed_cost": landed_cost,
            "fba_fee_estimate": analyzer.estimate_fba_fee("CABINET", 40, 36, False),
            "ad_spend": 0,  # requires Ads API for real data
            "refund_amount": 0,  # requires Finances API for real data
            "category": "CABINET",
        })

    if not sku_data:
        print("No products have cost/price data. Sync prices first (sync-prices).")
        return

    report = analyzer.analyze_batch(sku_data, category="CABINET")

    print(f"Products analyzed: {len(report.sku_breakdowns)}")
    print(f"Total Revenue: ${float(report.total_revenue):.2f}")
    print(f"Total Cost:    ${float(report.total_cost):.2f}")
    print(f"Total Profit:  ${float(report.total_profit):.2f}")
    print(f"Overall Margin: {float(report.overall_margin):.1%}")
    print("\nTop 5 Most Profitable:")
    for b in report.top_profitable:
        print(f"  {b.sku}: margin={float(b.margin):.1%}, profit=${float(b.net_profit):.2f}")
    if report.bottom_profitable:
        print("\nBottom 5 Least Profitable:")
        for b in report.bottom_profitable:
            print(f"  {b.sku}: margin={float(b.margin):.1%}, profit=${float(b.net_profit):.2f}")

    print(f"\nProfit analysis complete for {len(report.sku_breakdowns)} products.")
    print("Note: units_sold and ad_spend fields use 0 values — requires Orders/Ads API for full accuracy.")


def handle_inventory_health(db: Session, **kwargs):
    """Run inventory health analysis using real giga_inventory data."""
    from src.services.inventory_planner import InventoryPlanner

    print("\nInventory Health Report\n" + "=" * 60)

    planner = InventoryPlanner()

    # Pull real inventory data from giga_inventory
    from sqlalchemy import text
    inv_rows = db.execute(
        text("SELECT giga_sku, quantity FROM giga_inventory ORDER BY giga_sku")
    ).fetchall()

    if not inv_rows:
        print("No inventory data found. Run sync-inventory first.")
        return

    print(f"Found {len(inv_rows)} inventory records.\n")

    # Resolve names
    giga_skus = [r[0] for r in inv_rows]
    giga_to_name = _resolve_giga_to_name(db, giga_skus)

    items = []
    for row in inv_rows:
        giga_sku = row[0]
        quantity = int(row[1]) if row[1] else 0
        name = giga_to_name.get(giga_sku, giga_sku)
        items.append({
            "sku": giga_sku,
            "asin": "",
            "product_name": name,
            "current_stock": quantity,
            "fba_stock": 0,  # requires FBA Inventory API
            "reserved_stock": 0,
            "units_sold_7d": 0,  # requires Orders API
            "units_sold_30d": 0,
        })

    report = planner.analyze(items)

    print(f"Total: {report.total_skus} | Healthy: {report.healthy_skus} | Low: {report.low_stock_skus}")
    print(f"Critical: {report.critical_stock_skus} | Excess: {report.excess_stock_skus} | Stale: {report.stale_stock_skus}")
    print(f"\nItems Needing Action ({len(report.items_needing_action)}):")
    for item in report.items_needing_action[:15]:
        print(f"  {item.sku}: {item.stock_status} ({item.days_of_stock:.0f} days stock), recommended order: {item.recommended_order_qty}")

    if report.liquidation_suggestions:
        print(f"\nLiquidation Suggestions ({len(report.liquidation_suggestions)}):")
        for s in report.liquidation_suggestions[:5]:
            print(f"  • {s}")

    print("\nInventory analysis complete.")
    print("Note: units_sold uses 0 values — requires Orders API for velocity-based recommendations.")


def handle_lifecycle_summary(db: Session, **kwargs):
    """Display product lifecycle summary using real product data."""
    from src.services.product_lifecycle_service import (
        ProductLifecycleManager,
        LifecycleStage,
        STAGE_LABELS,
    )
    from sqlalchemy import text

    manager = ProductLifecycleManager()

    # Get all products with meow_sku from meow_sku_map
    map_rows = db.execute(
        text("SELECT meow_sku, vendor_sku FROM meow_sku_map ORDER BY meow_sku")
    ).fetchall()

    if not map_rows:
        print("No products found in SKU mapping. Run sync-products first.")
        return

    # Get listing log for status inference
    listed_rows = db.execute(
        text("SELECT meow_sku, status FROM amz_listing_log")
    ).fetchall()
    listed_map = {r[0]: r[1] for r in listed_rows}

    # Get active listings for ASIN lookup
    active = _get_active_listings(db)
    active_skus = {item["sku"] for item in active}

    # Infer lifecycle stage from available data
    stage_counts = {s: 0 for s in LifecycleStage}
    for row in map_rows:
        meow_sku = row[0]
        log_status = listed_map.get(meow_sku, "")

        if log_status in ("PUBLISHED", "LISTED") or meow_sku in active_skus:
            stage = LifecycleStage.GROWING  # Assume growing once listed
        elif log_status == "GENERATED":
            stage = LifecycleStage.PREPARING
        else:
            stage = LifecycleStage.SELECTED

        manager.register(meow_sku, stage=stage)
        stage_counts[stage] += 1

    print("\n" + "=" * 60)
    print("Product Lifecycle Summary")
    print("=" * 60)

    summary = manager.get_lifecycle_summary()
    for stage_name, count in summary.items():
        label = STAGE_LABELS.get(LifecycleStage(stage_name), stage_name)
        bar = "█" * min(count, 40)
        print(f"  {label:8s} ({stage_name:12s}): {count:3d} {bar}")

    print(f"\nTotal products tracked: {sum(summary.values())}")

    # Show tasks per stage
    for stage in LifecycleStage:
        rec = manager.get_stage_recommendations(stage)
        if rec["product_count"] > 0:
            print(f"\n📋 {rec['label']} ({rec['product_count']} products)")
            print(f"   Focus: {rec['key_focus']}")
            for task in rec["tasks"][:3]:
                tag = "🤖" if task["auto"] else "👤"
                print(f"   {tag} {task['label']}")

    print()


def handle_daily_check(db: Session, **kwargs):
    """Run the daily health check and push alerts."""
    from src.services.daily_check_service import run_daily_check

    print("\nRunning daily health check...\n")
    result = run_daily_check(db, notify=True)
    print(f"Overall Status: {result.overall_status}")
    for section_title, section_body in result.sections.items():
        print(f"\n{section_title}:")
        print(f"  {section_body}")
    if result.alerts:
        print(f"\n{len(result.alerts)} alerts pushed to Feishu.")
    else:
        print("\nNo alerts. All systems normal.")


def handle_test_feishu_alert(db: Session, **kwargs):
    """Send a Feishu webhook smoke-test card."""
    from infrastructure.feishu_client import FeishuClient, FeishuMessage

    feishu = FeishuClient.from_env()
    if not feishu.is_configured:
        print("\nFEISHU_WEBHOOK_URL is not configured.")
        print("Add it to .env, rebuild/restart the container, then retry.")
        return

    ok = feishu.send(
        FeishuMessage(
            title="Amazon Listing 系统 — 飞书连通性测试",
            content="如果你看到这条消息，说明 `FEISHU_WEBHOOK_URL` 配置正确。",
            severity="P2",
            tags=["连通性测试"],
        )
    )
    print("\nFeishu smoke test:", "OK" if ok else "FAILED")


def handle_amazon_order_daily_report(db: Session, **kwargs):
    """Send the 24h Amazon order health summary to Feishu."""
    from src.services.amazon_order_daily_report_service import (
        AmazonOrderDailyReportService,
    )

    print("\n" + "=" * 70)
    print("Amazon Order Daily Report")
    print("=" * 70)

    try:
        service = AmazonOrderDailyReportService(db=db)
        result = service.run_and_notify()
        print(
            f"\nWindow: {result['hours']}h | "
            f"New orders: {result['order_stats'].get('new_orders', 0)} | "
            f"Sync runs: {result['sync_stats'].get('total_runs', 0)} | "
            f"Feishu sent: {result['notified']}"
        )
    except Exception as e:
        print(f"\nAmazon order daily report failed: {e}")
        logging.exception("Detailed error:")


def handle_sync_amazon_orders(db: Session, **kwargs):
    """Sync Amazon MFN orders and notify humans about new unshipped orders."""
    from infrastructure.feishu_client import FeishuClient
    from src.services.amazon_order_sync_service import AmazonOrderSyncService

    notify_env = os.getenv("AMAZON_ORDER_SYNC_NOTIFY", "true").lower()
    notify = notify_env not in {"0", "false", "no"}

    logger.info("Starting Amazon order sync (notify=%s)", notify)
    print("\n" + "=" * 70)
    print(f"Amazon Order Sync - notify={'ON' if notify else 'OFF'}")
    print("=" * 70)

    if notify and not FeishuClient.from_env().is_configured:
        print(
            "\nWarning: FEISHU_WEBHOOK_URL is not set. "
            "Orders will sync to DB but no Feishu alerts will be sent."
        )

    try:
        service = AmazonOrderSyncService(db=db)
        result = service.sync_and_notify(notify=notify)
        print(
            f"\nFetched: {result['fetched_count']} | "
            f"New: {result['new_count']} | "
            f"Notified: {result['notified_count']} | "
            f"Errors: {result['error_count']}"
        )
    except Exception as e:
        print(f"\nAmazon order sync failed: {e}")
        logging.exception("Detailed error:")


def handle_update_package_dimensions(db: Session, dry_run: bool = True):
    """PATCH item_package_dimensions / weight / quantity for combo products."""
    from src.services.amazon_package_dimensions_service import (
        AmazonPackageDimensionsService,
    )

    logger.info("Starting package dimensions update (dry_run=%s)", dry_run)
    print("\n" + "=" * 70)
    mode_label = "DRY RUN" if dry_run else "LIVE"
    print(f"Package Dimensions Update - {mode_label}")
    print("=" * 70)

    limit_text = os.getenv("PACKAGE_DIMS_LIMIT")
    limit = int(limit_text) if limit_text else None
    try:
        service = AmazonPackageDimensionsService(db=db)
        service.submit_package_dimensions(dry_run=dry_run, limit=limit)
    except Exception as e:
        print(f"\nPackage dimensions update failed: {e}")
        logging.exception("Detailed error:")
        raise


def handle_delete_orphan_listings(db: Session, dry_run: bool = True):
    """Delete live legacy Amazon listings that have no Giga mapping in meow_sku_map."""
    from src.services.amazon_listing_cleanup_service import (
        AmazonListingCleanupService,
    )

    logger.info("Starting orphan listing cleanup (dry_run=%s)", dry_run)
    print("\n" + "=" * 70)
    mode_label = "DRY RUN" if dry_run else "LIVE DELETE"
    print(f"Orphan Listing Cleanup - {mode_label}")
    print("=" * 70)

    limit_text = os.getenv("CLEANUP_LIMIT")
    limit = int(limit_text) if limit_text else None
    try:
        service = AmazonListingCleanupService(db=db)
        service.delete_orphan_listings(dry_run=dry_run, limit=limit)
    except Exception as e:
        print(f"\nOrphan listing cleanup failed: {e}")
        logging.exception("Detailed error:")
        raise


def handle_analyze_listing_requirements_v2(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
):
    """Read-only V2 requirement tree analysis for one SKU."""
    from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2

    sku = (sku_list or [None])[0]
    if not product_type:
        raise ValueError("--product-type or --category is required")
    if not sku:
        raise ValueError("--sku is required")

    print("\n" + "=" * 70)
    print("Listing Requirement Analysis V2 - READ ONLY")
    print("=" * 70)

    service = ListingPayloadEngineV2(db=db)
    result = service.analyze_requirements(product_type=product_type, sku=sku)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def handle_validate_listing_v2(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
):
    """Run Amazon VALIDATION_PREVIEW for a V2 plan without PUT."""
    from src.services.attribute_rule_loader import AttributeRuleLoader
    from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
    from src.services.validation_preview_v2 import ValidationPreviewV2

    sku = (sku_list or [None])[0]
    if not product_type:
        raise ValueError("--product-type or --category is required")
    if not sku:
        raise ValueError("--sku is required")

    print("\n" + "=" * 70)
    print("Listing Validation Preview V2 - AMAZON VALIDATION_PREVIEW (no PUT)")
    print("=" * 70)

    rules = AttributeRuleLoader().load(product_type)
    plan = ListingPayloadEngineV2(db=db).build_read_only_plan(
        product_type=product_type,
        sku=sku,
        rules=rules,
    )
    preview = ValidationPreviewV2(db=db)
    result = preview.preview(plan)
    comparison = preview.compare(plan, result)

    print(
        f"\nSKU={sku} product_type={product_type} "
        f"status={result.status} request_id={result.amazon_request_id} "
        f"amazon_issues={len(result.issues)} "
        f"v2_findings={len(plan.findings or [])}"
    )
    print(
        f"comparison: matched={len(comparison.matched)} "
        f"amazon_only={len(comparison.amazon_only)} "
        f"v2_only={len(comparison.v2_only)}"
    )
    if comparison.amazon_only:
        print("\nAmazon flagged but V2 missed:")
        for issue in comparison.amazon_only:
            attrs = issue.get("attributeNames") or []
            print(f"  [{issue.get('code')}] {issue.get('message')} ({', '.join(attrs)})")
    if comparison.v2_only:
        print("\nV2 flagged but Amazon accepted:")
        for finding in comparison.v2_only:
            print(f"  [{finding.get('code')}] {finding.get('path_key')}")
    return {
        "success": True,
        "status": result.status,
        "amazon_issues": len(result.issues),
        "v2_findings": len(plan.findings or []),
        "comparison": {
            "matched": len(comparison.matched),
            "amazon_only": len(comparison.amazon_only),
            "v2_only": len(comparison.v2_only),
        },
    }


def handle_learn_required_from_submissions(
    db: Session,
    product_type: Optional[str] = None,
):
    """Learn V2 required path_keys from Amazon 90220 missing-required feedback."""
    from src.services.feedback_learning_adapter_v2 import FeedbackLearningAdapterV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    print("\n" + "=" * 70)
    print(f"V2 Feedback Learning - Amazon 90220 missing-required (category={product_type})")
    print("=" * 70)

    adapter = FeedbackLearningAdapterV2(db=db)
    summary = adapter.learn_from_recent_submissions(category=product_type, limit=100)
    learned_paths = adapter.get_learned_required_paths(category=product_type)

    print(
        f"\nsubmissions_scanned={summary['submissions_scanned']} "
        f"paths_learned={summary['paths_learned']}"
    )
    print(f"learned required path_keys for {product_type}: {len(learned_paths)}")
    for path_key in learned_paths:
        print(f"  {path_key}")
    return {"success": True, **summary, "learned_paths": learned_paths}
