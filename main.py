"""
Amazon Listing Management System - Main Entry Point
主程序入口 - 完整功能版本
"""
import sys
import logging
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
import argparse

# 加载环境变量
# 加载配置
from src.config.settings import settings

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from infrastructure.db_pool import SessionLocal, db_manager
from sqlalchemy import text

# 原有服务导入
from src.services.giga_sync_service import GigaSyncService
from src.services.giga_price_sync_service import GigaPriceSyncService
from src.services.giga_inventory_sync_service import GigaInventorySyncService
from src.services.product_detail_generation_service import ProductDetailGenerationService
from src.services.sku_mapping_service import SkuMappingService
from src.services.amz_full_list_importer_service import AmzFullListImporterService
from src.services.pricing_service import PricingService
from src.services.amz_asin_family_parent_listing_status_manager import ListingStatusManager

# 新服务导入
from src.services.product_listing_service import ProductListingService


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
# 减少SQLAlchemy日志输出
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


def print_header():
    """打印系统标题"""
    print("\n" + "="*70)
    print("🚀 Amazon Listing Management System")
    print("   电商自动化运营系统")
    print("="*70)


def print_menu():
    """显示主菜单"""
    print("\n" + "-"*70)
    print("📋 主菜单")
    print("-"*70)
    print("\n【1】Giga 商品管理")
    print("  1.1 同步全量Giga收藏商品详情")
    print("  1.2 导入亚马逊全量listing数据")
    print("  1.3 更新亚马逊父品发品状态")
    print("  1.4 使用AI生成商品详情（并自动映射SKU）")
    print("  1.5 同步Giga商品价格")
    print("  1.6 同步Giga商品库存")
    print("  1.7 更新售价")
    print("  1.8 生成亚马逊发品文件 ⭐")
    print("\n【2】数据查询")
    print("  2.1 查看数据统计")
    print("  2.2 查看待发品统计")
    print("  2.3 查看最近发品记录")
    print("\n【3】类目配置")
    print("  3.1 列出所有可用品类")
    print("  3.2 解析新的亚马逊类目模板到数据库")
    print("  3.3 从亚马逊报错文件自动矫正模板规则")
    print("  3.4 更新需要维护的品类(来自Giga) ⭐")
    print("  3.5 从CSV批量更新品类映射 ⭐")
    print("\n【4】系统维护")
    print("  4.1 从CSV批量同步SKU映射 🚧 (待实现)")
    print("\n【5】亚马逊运营每日常规 ⭐")
    print("  5.1 (一键) 生成亚马逊价格与库存更新文件")
    print("\n【0】退出系统")
    print("-"*70)


# ========================================================================
# 原有功能处理函数
# ========================================================================

def handle_sync_products(db: Session, auto_confirm: bool = False):
    """1.1 同步全量Giga收藏商品详情"""
    logger.info("🚀 启动商品同步流程...")
    
    service = GigaSyncService(db)
    
    print("\n➡️  步骤 1/2: 获取收藏商品列表...")
    sku_list = service.get_full_sku_list()  # 修正：使用正确的方法名
    
    if not sku_list:
        print("✅ 没有收藏商品需要同步")
        return
    
    print(f"✅ 获取到 {len(sku_list)} 个收藏商品")
    
    if not auto_confirm:
        if sys.stdin and sys.stdin.isatty():
            confirm = input(f"⚠️  即将同步 {len(sku_list)} 个商品的详情，是否继续? (y/n): ").strip().lower()
            if confirm != 'y':
                print("\n❌ 操作已取消")
                return
        else:
            print(f"⚠️  即将同步 {len(sku_list)} 个商品的详情")
            print("❌ 错误: 在 Web 界面运行此任务时，请务必勾选 '自动确认 (Auto Confirm)'")
            return

    print(f"\n➡️  步骤 2/2: 同步商品详情...")
    
    total, success, failed = service.sync_product_details(sku_list)
    
    print(f"\n{'='*60}")
    print("✅ 商品同步完成")
    print(f"{'='*60}")
    print(f"总计: {total}")
    print(f"成功: {success}")
    print(f"失败: {failed}")
    print(f"{'='*60}\n")


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
    print("\n" + "="*70)
    print("📦 更新亚马逊父品发品状态")
    print("="*70)
    
    try:
        manager = ListingStatusManager(db=db)
        manager.update_statuses_to_listed()
        print("="*70)
    except Exception as e:
        print(f"\n❌ 执行发品状态更新时发生错误: {e}")
        logging.exception("详细错误:")


def handle_generate_details(db: Session):
    """1.4 使用AI生成商品详情"""
    logger.info("🚀 启动AI详情生成流程...")
    
    # LLM配置从环境变量自动读取
    llm_provider = os.getenv("LLM_PROVIDER", "deepseek").upper()
    print(f"\n🤖 使用 {llm_provider} 模型（从环境变量读取）")
    
    # 修正：使用正确的参数初始化
    service = ProductDetailGenerationService(db=db)
    
    service.process_all_skus()
    
    # 自动触发SKU映射
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
    
    # 更新所有SKU的价格
    total, success, report_data = service.update_prices()
    
    # 显示样例数据
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


def handle_view_statistics(db: Session):
    """2.1 查看数据统计"""
    from src.repositories.giga_product_sync_repository import GigaProductSyncRepository
    from src.repositories.llm_product_detail_repository import LLMProductDetailRepository
    from src.repositories.sku_mapping_repository import SkuMappingRepository
    from src.repositories.giga_product_price_repository import GigaProductPriceRepository
    from src.repositories.giga_product_inventory_repository import GigaProductInventoryRepository
    from src.repositories.amz_full_list_report_repository import AmzFullListReportRepository
    
    print("\n" + "="*70)
    print("📊 数据统计")
    print("="*70)
    
    try:
        # Amazon数据
        amz_repo = AmzFullListReportRepository(db)
        amz_stats = amz_repo.get_statistics()
        print("\n【Amazon数据】")
        print(f"  总记录: {amz_stats.get('total_records', amz_stats.get('total', 'N/A'))}")
        print(f"  Active: {amz_stats.get('active_listings', amz_stats.get('active', 'N/A'))}")
        print(f"  唯一ASIN: {amz_stats.get('unique_asins', 'N/A')}")
    except Exception as e:
        print(f"\n【Amazon数据】")
        print(f"  查询失败: {e}")
    
    try:
        # Giga商品
        giga_repo = GigaProductSyncRepository(db)
        giga_stats = giga_repo.get_statistics()
        print("\n【Giga商品】")
        print(f"  总记录: {giga_stats.get('total_products', giga_stats.get('total', 'N/A'))}")
        print(f"  已同步: {giga_stats.get('synced_products', 'N/A')}")
        print(f"  超大件: {giga_stats.get('oversized_products', 'N/A')}")
    except Exception as e:
        print(f"\n【Giga商品】")
        print(f"  查询失败: {e}")
    
    try:
        # LLM生成详情
        llm_repo = LLMProductDetailRepository(db)
        llm_stats = llm_repo.get_statistics()
        print("\n【LLM生成详情】")
        print(f"  总记录: {llm_stats.get('total_details', llm_stats.get('total', 'N/A'))}")
        print(f"  唯一SKU: {llm_stats.get('unique_skus', 'N/A')}")
    except Exception as e:
        print(f"\n【LLM生成详情】")
        print(f"  查询失败: {e}")
    
    try:
        # SKU映射
        mapping_repo = SkuMappingRepository(db)
        mapping_stats = mapping_repo.get_statistics()
        print("\n【SKU映射】")
        print(f"  总映射: {mapping_stats.get('total_mappings', mapping_stats.get('total', 'N/A'))}")
        print(f"  供应商数: {mapping_stats.get('unique_vendors', 'N/A')}")
    except Exception as e:
        print(f"\n【SKU映射】")
        print(f"  查询失败: {e}")
    
    try:
        # Giga价格
        price_repo = GigaProductPriceRepository(db)
        price_stats = price_repo.get_statistics()
        print("\n【Giga价格】")
        print(f"  总价格: {price_stats.get('total_prices', price_stats.get('total', 'N/A'))}")
        print(f"  可用SKU: {price_stats.get('available_skus', 'N/A')}")
        print(f"  价格梯度: {price_stats.get('total_tiers', 'N/A')}")
    except Exception as e:
        print(f"\n【Giga价格】")
        print(f"  查询失败: {e}")
    
    try:
        # Giga库存
        inventory_repo = GigaProductInventoryRepository(db)
        inventory_stats = inventory_repo.get_statistics()
        print("\n【Giga库存】")
        print(f"  总SKU: {inventory_stats.get('total_skus', 'N/A')}")
        print(f"  有库存: {inventory_stats.get('in_stock_skus', 'N/A')}")
        print(f"  总库存量: {inventory_stats.get('total_quantity', 'N/A')}")
    except Exception as e:
        print(f"\n【Giga库存】")
        print(f"  查询失败: {e}")
    
    print("="*70 + "\n")


# ========================================================================
# 新增功能：发品管理
# ========================================================================

def handle_generate_listing(db: Session, category: Optional[str] = None):
    """1.8 生成亚马逊发品文件"""
    print("\n" + "="*70)
    print("📦 生成亚马逊发品文件")
    print("="*70)
    
    if not category:
        print("\n可用品类:")
        print("  1. CABINET")
        print("  2. HOME_MIRROR")
        print("  0. 返回主菜单")
        choice = input("\n请选择品类 (输入编号): ").strip()
        category_map = {
            "1": "CABINET",
            "2": "HOME_MIRROR"
        }
        if choice == "0":
            return
        category = category_map.get(choice)
        if not category:
            print("❌ 无效的选择")
            return
    
    print(f"\n📦 开始处理品类: {category}")
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")
    
    try:
        service = ProductListingService(db=db)
        result = service.generate_listings_by_category(category)
        
        print("\n" + "="*70)
        if result['success']:
            print("✅ 发品文件生成成功！")
            print("="*70)
            print(f"📊 统计信息:")
            print(f"   - 单品数量: {result.get('single_count', 0)}")
            print(f"   - 变体家族: {result.get('variation_count', 0)}")
            print(f"   - 总行数: {result.get('total_rows', 0)}")
            print(f"   - 批次ID: {result.get('batch_id', 'N/A')}")
            
            if 'excel_file' in result:
                print(f"\n📁 输出文件:")
                print(f"   {result['excel_file']}")
            
            print("="*70)
            return result
        else:
            print("❌ 发品文件生成失败")
            print("="*70)
            print(f"💡 原因: {result.get('message', '未知错误')}")
            print("="*70)
            return result
    
    except Exception as e:
        print("\n" + "="*70)
        print("❌ 系统错误")
        print("="*70)
        print(f"错误信息: {str(e)}")
        print("="*70)
        logging.exception("详细错误:")
        return None


def handle_pending_statistics(db: Session):
    """2.2 查看待发品统计"""
    print("\n" + "="*70)
    print("📊 待发品统计")
    print("="*70)
    
    try:
        query = text("""
            SELECT 
                COUNT(DISTINCT m.meow_sku) as total_pending,
                COUNT(DISTINCT CASE WHEN scm.standard_category_name = 'cabinet' THEN m.meow_sku END) as cabinet_count,
                COUNT(DISTINCT CASE WHEN scm.standard_category_name = 'home_mirror' THEN m.meow_sku END) as mirror_count
            FROM meow_sku_map m
                LEFT JOIN amz_all_listing_report r 
                    ON m.meow_sku = r."seller-sku"
                JOIN giga_product_sync_records psr 
                    ON m.vendor_sku = psr.giga_sku 
                    AND m.vendor_source = 'giga'
                JOIN giga_product_base_prices pbp 
                    ON m.vendor_sku = pbp.giga_sku
                LEFT JOIN supplier_categories_map scm 
                    ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
                    AND scm.supplier_platform = 'giga'
            WHERE r."seller-sku" IS NULL
              AND psr.is_oversize IS NOT TRUE
              AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'
              AND pbp.sku_available IS TRUE;
        """)
        
        result = db.execute(query).fetchone()
        
        print()
        print(f"   总待发品数: {result[0]}")
        print(f"   - CABINET: {result[1]}")
        print(f"   - HOME_MIRROR: {result[2]}")
        print(f"   - 其他品类: {result[0] - result[1] - result[2]}")
        print("="*70)
    
    except Exception as e:
        print(f"❌ 查询统计失败: {e}")


def handle_recent_listings(db: Session):
    """2.3 查看最近发品记录"""
    print("\n" + "="*70)
    print("📜 最近发品记录（最近10条）")
    print("="*70)
    
    try:
        query = text("""
            SELECT 
                listing_batch_id,
                COUNT(*) as sku_count,
                COUNT(*) FILTER (WHERE parent_sku = 'SINGLE_PRODUCT') as single_count,
                COUNT(*) FILTER (WHERE parent_sku != 'SINGLE_PRODUCT') as variation_count,
                status,
                MIN(created_at) as created_at
            FROM amz_listing_log
            GROUP BY listing_batch_id, status
            ORDER BY created_at DESC
            LIMIT 10;
        """)
        
        result = db.execute(query).fetchall()
        
        if result:
            print()
            for i, row in enumerate(result, 1):
                batch_id = str(row[0])[:8]
                print(f"   {i}. 批次 {batch_id}... | SKU数: {row[1]} | 单品: {row[2]} | 变体: {row[3]} | 状态: {row[4]}")
                print(f"      时间: {row[5].strftime('%Y-%m-%d %H:%M:%S') if row[5] else 'N/A'}")
        else:
            print("   暂无发品记录")
        
        print("="*70)
    
    except Exception as e:
        print(f"❌ 查询记录失败: {e}")


# ========================================================================
# 类目配置功能
# ========================================================================

def handle_list_categories(db: Session):
    """3.1 列出所有可用品类"""
    print("\n" + "="*70)
    print("📋 可用品类列表")
    print("="*70)
    
    try:
        query = text("""
            SELECT DISTINCT standard_category_name
            FROM supplier_categories_map
            WHERE supplier_platform = 'giga'
              AND standard_category_name IS NOT NULL
              AND standard_category_name != ''
            ORDER BY standard_category_name;
        """)
        
        result = db.execute(query).scalars().all()
        
        if result:
            print()
            for i, category in enumerate(result, 1):
                print(f"   {i}. {category}")
            print(f"\n总计: {len(result)} 个品类")
        else:
            print("   暂无品类数据")
        
        print("="*70)
    
    except Exception as e:
        print(f"❌ 查询品类失败: {e}")


def handle_template_update(db: Session, template_path: Optional[str] = None, category_name: Optional[str] = None):
    """3.2 解析新的亚马逊类目模板到数据库"""
    from src.services.amz_template_management_service import TemplateManagementService
    
    logger.info("🚀 启动更新亚马逊类目模板流程...")
    print("\n" + "="*70)
    print("📦 解析新的亚马逊类目模板")
    print("="*70)
    
    try:
        if not template_path:
            template_path = input(
                "\n请输入亚马逊模板文件(.xlsm)的完整路径: "
            ).strip().strip('"')
        if not category_name:
            category_name = input(
                "请输入该模板对应的品类名称 (例如 HOME_MIRROR): "
            ).strip()
        
        if not os.path.exists(template_path) or not category_name:
            print("❌ 文件路径和品类名称均不能为空，操作取消。")
            return
        
        service = TemplateManagementService(db=db)
        success, message = service.update_template_from_file(
            template_path, 
            category_name
        )
        
        if success:
            print(f"\n✅ {message}")
        else:
            print(f"\n❌ {message}")
            
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ 更新亚马逊类目模板时发生错误: {e}")
        logging.exception("详细错误:")


def handle_template_correction(db: Session, report_path: Optional[str] = None, category_name: Optional[str] = None):
    """3.3 从亚马逊报错文件自动矫正模板规则"""
    from src.services.amz_template_management_service import TemplateManagementService
    
    logger.info("🚀 启动模板规则自动矫正流程...")
    print("\n" + "="*70)
    print("📦 从报错文件矫正模板规则")
    print("="*70)
    
    try:
        if not report_path:
            report_path = input(
                "\n请输入亚马逊报错文件(.xlsm)的完整路径: "
            ).strip().strip('"')
        if not category_name:
            category_name = input(
                "请输入该报错文件对应的品类名称 (例如 HOME_MIRROR): "
            ).strip()

        if not os.path.exists(report_path) or not category_name:
            print("❌ 文件路径和品类名称均不能为空，操作取消。")
            return

        service = TemplateManagementService(db=db)
        success, message = service.correct_rules_from_report(
            report_path, 
            category_name
        )
        
        if success:
            print(f"\n✅ 完成")
        else:
            print(f"\n❌ 失败")
            
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ 执行模板规则矫正时发生错误: {e}")
        logging.exception("详细错误:")


def handle_sync_giga_categories(db: Session, auto_confirm: bool = False, export: bool = False):
    """3.4 更新需要维护的品类(来自Giga)"""
    from src.services.category_maintenance_service import CategoryMaintenanceService
    
    logger.info("🚀 启动Giga品类同步流程...")
    print("\n" + "="*70)
    print("🔄 更新需要维护的品类(来自Giga)")
    print("="*70)
    
    print("\n功能说明:")
    print("  1. 从 giga_product_sync_records 查询所有品类代码")
    print("  2. 对比 supplier_categories_map 中已存在的映射")
    print("  3. 将新品类插入到映射表中")
    print("  4. standard_category_name 留空，待后续手动维护")
    print()
    
    try:
        if not auto_confirm:
            if sys.stdin and sys.stdin.isatty():
                confirm = input("是否继续执行? (y/n): ").strip().lower()
                if confirm != 'y':
                    print("\n❌ 操作已取消")
                    print("="*70)
                    return
            else:
                print("❌ 错误: 在 Web 界面运行此任务时，请务必勾选 '自动确认 (Auto Confirm)'")
                print("="*70)
                return
        
        # 执行同步
        service = CategoryMaintenanceService(db)
        result = service.sync_giga_categories()
        
        # 根据结果决定是否导出待维护列表
        if result.get('inserted_count', 0) > 0:
            print()
            if export:
                export_new_categories(result.get('new_category_list', []))
            elif sys.stdin and sys.stdin.isatty():
                choice = input("是否导出新增品类列表到CSV文件? (y/n): ").strip().lower()
                if choice == 'y':
                    export_new_categories(result.get('new_category_list', []))
            else:
                print("⚠️  非交互模式，跳过导出 CSV 询问")
        
    except Exception as e:
        print(f"\n❌ 品类同步失败: {e}")
        logging.exception("详细错误:")


def export_new_categories(categories: List[Dict]):
    """
    导出新增品类列表到 CSV 文件
    
    Args:
        categories: 新增的品类列表
    """
    import csv
    
    if not categories:
        print("⚠️  没有新品类需要导出")
        return
    
    # 创建输出目录
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"new_giga_categories_{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)
    
    try:
        # 写入 CSV
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(
                f, 
                fieldnames=['category_code', 'category_name', 'standard_category_name']
            )
            writer.writeheader()
            
            for cat in categories:
                writer.writerow({
                    'category_code': cat['category_code'],
                    'category_name': cat['category_name'],
                    'standard_category_name': ''  # 待维护
                })
        
        print(f"\n✅ 新品类列表已导出到: {filepath}")
        print("   请在此文件中填写 standard_category_name，然后可以批量导入")
        
    except Exception as e:
        print(f"❌ 导出失败: {e}")


def handle_update_mappings_from_csv(db: Session, csv_file_path: Optional[str] = None):
    """3.5 从CSV批量更新品类映射"""
    from src.services.category_maintenance_service import CategoryMaintenanceService
    
    logger.info("🚀 启动从CSV批量更新品类映射流程...")
    print("\n" + "=" * 70)
    print("📥 从 CSV 批量更新品类映射")
    print("=" * 70)
    
    print("\n📋 CSV 文件格式说明:")
    print("   必需字段（请严格按照以下字段名，区分大小写）:")
    print("   1. supplier_platform       - 供应商平台 (如: giga)")
    print("   2. supplier_category_code  - 供应商品类代码")
    print("   3. standard_category_name  - 标准品类名称")
    print()
    print("   示例 CSV 内容:")
    print("   supplier_platform,supplier_category_code,standard_category_name")
    print("   giga,CAB001,cabinet")
    print("   giga,TAB100,dining_table")
    print("   giga,MIR300,home_mirror")
    print()
    print("   ⚠️  注意事项:")
    print("   - standard_category_name 必须是系统中已存在的亚马逊品类")
    print("   - 只会更新 supplier_platform + supplier_category_code 匹配的记录")
    print("   - 不匹配的记录不会更新")
    print()
    
    try:
        if not csv_file_path:
            csv_file_path = input("请输入 CSV 文件路径: ").strip().strip('"')
        
        if not csv_file_path:
            print("\n❌ 未提供文件路径，操作取消")
            print("=" * 70)
            return
        
        # 执行更新
        service = CategoryMaintenanceService(db)
        result = service.update_mappings_from_csv(csv_file_path)
        
        print()
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ 批量更新失败: {e}")
        logging.exception("详细错误:")


# ========================================================================
# 系统维护功能
# ========================================================================

def handle_sku_sync_from_csv(db: Session):
    """4.1 从CSV批量同步SKU映射"""
    print("\n" + "="*70)
    print("📦 从CSV批量同步SKU映射")
    print("="*70)
    print("\n⚠️  此功能暂未实现，请等待后续版本。")
    print("="*70)


# ========================================================================
# 亚马逊运营每日常规
# ========================================================================

def handle_generate_update_file(db: Session):
    """5.1 (一键) 生成亚马逊价格与库存更新文件"""
    from src.services.amz_inventory_price_updater_service import InventoryPriceUpdaterService
    
    logger.info("🚀 启动生成亚马逊库存价格更新文件流程...")
    print("\n" + "="*70)
    print("📦 (一键) 生成亚马逊价格与库存更新文件")
    print("="*70)
    
    try:
        service = InventoryPriceUpdaterService(db=db)
        service.generate_update_file()
    except Exception as e:
        print(f"\n❌ 生成更新文件时发生错误: {e}")
        logging.exception("详细错误:")


# ========================================================================
# 主程序
# ========================================================================

def main():
    """主程序"""
    load_dotenv()
    logger.info("系统启动")
    
    parser = argparse.ArgumentParser(description="Amazon Listing Management System")
    parser.add_argument("--task", help="任务标识，如: sync-products, generate-update-file, generate-listing 等")
    parser.add_argument("--category", help="品类名称，如 CABINET 或 HOME_MIRROR")
    parser.add_argument("--file", help="文件路径，用于需要文件输入的任务")
    parser.add_argument("--auto-confirm", action="store_true", help="自动确认，避免交互式提示")
    args = parser.parse_args()

    non_interactive_task = args.task or os.getenv("APP_TASK")
    param_category = args.category or os.getenv("LISTING_CATEGORY")
    param_file = args.file or os.getenv("INPUT_FILE_PATH")
    auto_confirm = args.auto_confirm or (os.getenv("AUTO_CONFIRM", "false").lower() == "true")

    if non_interactive_task:
        try:
            with SessionLocal() as db:
                t = non_interactive_task.strip().lower()
                if t == "sync-products":
                    handle_sync_products(db, auto_confirm=auto_confirm)
                elif t == "import-amz-report":
                    handle_import_amazon_report(db, file_path=param_file)
                elif t == "update-listing-status":
                    handle_update_listing_status(db)
                elif t == "generate-details":
                    handle_generate_details(db)
                elif t == "sync-prices":
                    handle_sync_prices(db)
                elif t == "sync-inventory":
                    handle_sync_inventory(db)
                elif t == "update-prices":
                    handle_update_prices(db)
                elif t == "generate-listing":
                    handle_generate_listing(db, category=param_category)
                elif t == "view-statistics":
                    handle_view_statistics(db)
                elif t == "pending-statistics":
                    handle_pending_statistics(db)
                elif t == "recent-listings":
                    handle_recent_listings(db)
                elif t == "list-categories":
                    handle_list_categories(db)
                elif t == "template-update":
                    handle_template_update(db, template_path=param_file, category_name=param_category)
                elif t == "template-correction":
                    handle_template_correction(db, report_path=param_file, category_name=param_category)
                elif t == "sync-giga-categories":
                    handle_sync_giga_categories(db, auto_confirm=auto_confirm)
                elif t == "update-mappings-from-csv":
                    handle_update_mappings_from_csv(db, csv_file_path=param_file)
                elif t == "generate-update-file":
                    handle_generate_update_file(db)
                else:
                    print(f"\n❌ 未知任务: {non_interactive_task}")
                    sys.exit(2)
            sys.exit(0)
        except KeyboardInterrupt:
            print("\n\n⚠️  程序被用户中断")
            logger.info("系统被用户中断")
            sys.exit(130)
        except Exception as e:
            logger.error(f"发生错误: {e}", exc_info=True)
            print(f"\n❌ 发生错误: {e}")
            sys.exit(1)

def run_task(task: str, category: Optional[str] = None, file_path: Optional[str] = None, auto_confirm: bool = False):
    load_dotenv()
    with SessionLocal() as db:
        t = task.strip().lower()
        if t == "sync-products":
            handle_sync_products(db, auto_confirm=auto_confirm)
            return None
        elif t == "import-amz-report":
            handle_import_amazon_report(db, file_path=file_path)
            return None
        elif t == "update-listing-status":
            handle_update_listing_status(db)
            return None
        elif t == "generate-details":
            handle_generate_details(db)
            return None
        elif t == "sync-prices":
            handle_sync_prices(db)
            return None
        elif t == "sync-inventory":
            handle_sync_inventory(db)
            return None
        elif t == "update-prices":
            handle_update_prices(db)
            return None
        elif t == "generate-listing":
            if category:
                service = ProductListingService(db=db)
                return service.generate_listings_by_category(category)
            return None
        elif t == "view-statistics":
            handle_view_statistics(db)
            return None
        elif t == "pending-statistics":
            handle_pending_statistics(db)
            return None
        elif t == "recent-listings":
            handle_recent_listings(db)
            return None
        elif t == "list-categories":
            handle_list_categories(db)
            return None
        elif t == "template-update":
            handle_template_update(db, template_path=file_path, category_name=category)
            return None
        elif t == "template-correction":
            handle_template_correction(db, report_path=file_path, category_name=category)
            return None
        elif t == "sync-giga-categories":
            handle_sync_giga_categories(db, auto_confirm=auto_confirm)
            return None
        elif t == "update-mappings-from-csv":
            handle_update_mappings_from_csv(db, csv_file_path=file_path)
            return None
        elif t == "generate-update-file":
            handle_generate_update_file(db)
            return None
        return None

    while True:
        try:
            print_header()
            print_menu()
            choice = input("\n请输入功能编号: ").strip()
            if choice == "0":
                print("\n👋 感谢使用！再见！\n")
                logger.info("系统退出")
                break
            with SessionLocal() as db:
                if choice == "1.1":
                    handle_sync_products(db)
                elif choice == "1.2":
                    handle_import_amazon_report(db)
                elif choice == "1.3":
                    handle_update_listing_status(db)
                elif choice == "1.4":
                    handle_generate_details(db)
                elif choice == "1.5":
                    handle_sync_prices(db)
                elif choice == "1.6":
                    handle_sync_inventory(db)
                elif choice == "1.7":
                    handle_update_prices(db)
                elif choice == "1.8":
                    handle_generate_listing(db)
                elif choice == "2.1":
                    handle_view_statistics(db)
                elif choice == "2.2":
                    handle_pending_statistics(db)
                elif choice == "2.3":
                    handle_recent_listings(db)
                elif choice == "3.1":
                    handle_list_categories(db)
                elif choice == "3.2":
                    handle_template_update(db)
                elif choice == "3.3":
                    handle_template_correction(db)
                elif choice == "3.4":
                    handle_sync_giga_categories(db)
                elif choice == "3.5":
                    handle_update_mappings_from_csv(db)
                elif choice == "4.1":
                    handle_sku_sync_from_csv(db)
                elif choice == "5.1":
                    handle_generate_update_file(db)
                else:
                    print("\n❌ 无效的选项，请重新输入")
            input("\n按回车键继续...")
        except KeyboardInterrupt:
            print("\n\n⚠️  程序被用户中断")
            logger.info("系统被用户中断")
            break
        except Exception as e:
            logger.error(f"发生错误: {e}", exc_info=True)
            print(f"\n❌ 发生错误: {e}")
            input("\n按回车键继续...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  程序被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 系统错误: {e}")
        logging.exception("系统错误详情:")
        sys.exit(1)
