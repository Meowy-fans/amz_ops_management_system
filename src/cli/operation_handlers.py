"""CLI handlers for operational tasks."""
import logging
import os
import sys
from typing import Optional

from sqlalchemy.orm import Session

from src.services.amz_asin_family_parent_listing_status_manager import ListingStatusManager
from src.services.amz_full_list_importer_service import AmzFullListImporterService
from src.services.giga_inventory_sync_service import GigaInventorySyncService
from src.services.giga_price_sync_service import GigaPriceSyncService
from src.services.giga_sync_service import GigaSyncService
from src.services.pricing_service import PricingService
from src.services.product_detail_generation_service import ProductDetailGenerationService
from src.services.sku_mapping_service import SkuMappingService

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

    print(f"\n➡️  步骤 2/2: 同步商品详情...")

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
