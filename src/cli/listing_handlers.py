"""CLI handlers for Amazon listing generation."""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.services.product_listing_service import ProductListingService


def handle_generate_listing(db: Session, category: Optional[str] = None):
    """1.8 生成亚马逊发品文件"""
    print("\n" + "=" * 70)
    print("📦 生成亚马逊发品文件")
    print("=" * 70)

    if not category:
        print("\n可用品类:")
        print("  1. CABINET")
        print("  2. HOME_MIRROR")
        print("  0. 返回主菜单")
        choice = input("\n请选择品类 (输入编号): ").strip()
        category_map = {
            "1": "CABINET",
            "2": "HOME_MIRROR",
        }
        if choice == "0":
            return
        category = category_map.get(choice)
        if not category:
            print("❌ 无效的选择")
            return

    print(f"\n📦 开始处理品类: {category}")
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")

    try:
        service = ProductListingService(db=db)
        result = service.generate_listings_by_category(category)

        print("\n" + "=" * 70)
        if result["success"]:
            print("✅ 发品文件生成成功！")
            print("=" * 70)
            print(f"📊 统计信息:")
            print(f"   - 单品数量: {result.get('single_count', 0)}")
            print(f"   - 变体家族: {result.get('variation_count', 0)}")
            print(f"   - 总行数: {result.get('total_rows', 0)}")
            print(f"   - 批次ID: {result.get('batch_id', 'N/A')}")

            if "excel_file" in result:
                print(f"\n📁 输出文件:")
                print(f"   {result['excel_file']}")

            print("=" * 70)
            return result
        else:
            print("❌ 发品文件生成失败")
            print("=" * 70)
            print(f"💡 原因: {result.get('message', '未知错误')}")
            print("=" * 70)
            return result

    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ 系统错误")
        print("=" * 70)
        print(f"错误信息: {str(e)}")
        print("=" * 70)
        logging.exception("详细错误:")
        return None


def handle_generate_listing_api(
    db: Session,
    category: Optional[str] = None,
    dry_run: bool = True,
):
    """1.9 通过Amazon SP-API提交新品发品"""
    print("\n" + "=" * 70)
    mode_label = "DRY RUN (预览)" if dry_run else "LIVE (真实提交)"
    print(f"Amazon SP-API 新品发品 - {mode_label}")
    print("=" * 70)

    if not category:
        print("\n可用品类:")
        print("  1. CABINET")
        print("  2. HOME_MIRROR")
        print("  0. 返回")
        choice = input("\n请选择品类 (输入编号): ").strip()
        category_map = {"1": "CABINET", "2": "HOME_MIRROR"}
        if choice == "0":
            return
        category = category_map.get(choice)
        if not category:
            print("无效的选择")
            return

    print(f"\n品类: {category}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")

    try:
        service = ProductListingService(db=db)
        result = service.generate_listings_via_api(
            category_name=category,
            dry_run=dry_run,
        )

        print("\n" + "=" * 70)
        if result["success"]:
            print(f"发品API完成: {len(result.get('results', []))} SKUs")
            for r in result.get("results", [])[:5]:
                print(f"  {r['sku']}: {r['status']}")
            if len(result.get("results", [])) > 5:
                print(f"  ... and {len(result['results']) - 5} more")
        else:
            print(f"失败: {result.get('message', '未知错误')}")
        print("=" * 70)
        return result

    except Exception as e:
        print(f"\n系统错误: {e}")
        logging.exception("详细错误:")
        return None
