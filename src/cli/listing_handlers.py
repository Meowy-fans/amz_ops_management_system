"""CLI handlers for Amazon listing generation."""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.services.product_listing_service import ProductListingService


# @retire(since="2026-06-15", replaced_by="handle_generate_listing_api", scheduled_removal="2026-07-31")
def handle_generate_listing(db: Session, category: Optional[str] = None):
    """Deprecated alias: route legacy listing generation to API-native listing."""
    print("\n[DEPRECATED] generate-listing / Excel 发品已停止作为主流程。")
    print("请使用 API-native 发品入口 generate-listing-api；当前命令将转发到 dry-run 预览。")
    return handle_generate_listing_api(db=db, category=category, dry_run=True)


# @retire(since="2026-06-15", replaced_by="handle_generate_listing_api", scheduled_removal="2026-07-31")
def handle_generate_listing_excel_deprecated(db: Session, category: Optional[str] = None):
    """Legacy Excel generation implementation kept for historical reference."""
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
            print("📊 统计信息:")
            print(f"   - 单品数量: {result.get('single_count', 0)}")
            print(f"   - 变体家族: {result.get('variation_count', 0)}")
            print(f"   - 总行数: {result.get('total_rows', 0)}")
            print(f"   - 批次ID: {result.get('batch_id', 'N/A')}")

            if "excel_file" in result:
                print("\n📁 输出文件:")
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
    strict_validation: bool = False,
    sku_list: Optional[list[str]] = None,
    sku_file: Optional[str] = None,
    only_not_on_amazon: bool = False,
    engine: str = "v1",
):
    """1.9 通过Amazon SP-API提交新品发品"""
    print("\n" + "=" * 70)
    if strict_validation and not dry_run:
        print("Amazon SP-API 新品发品 - 配置错误")
        print("=" * 70)
        print("strict validation 只能用于 dry-run；请移除 --no-dry-run 后重试。")
        return {
            "success": False,
            "message": "strict_validation_requires_dry_run",
            "results": [],
        }
    normalized_engine = str(engine or "v1").strip().lower()
    if normalized_engine == "v2" and not dry_run:
        print("Amazon SP-API 新品发品 - 配置错误")
        print("=" * 70)
        print("LISTING_PAYLOAD_ENGINE=v2 目前只允许 dry-run / strict-validation canary。")
        return {
            "success": False,
            "message": "v2_engine_requires_dry_run",
            "results": [],
        }
    if normalized_engine == "shadow" and not dry_run:
        print("Amazon SP-API 新品发品 - 配置错误")
        print("=" * 70)
        print("shadow engine 只能用于 dry-run / strict-validation evidence collection。")
        return {
            "success": False,
            "message": "shadow_engine_requires_dry_run",
            "results": [],
        }

    mode_label = (
        "STRICT DRY RUN (Amazon VALIDATION_PREVIEW)"
        if strict_validation
        else "DRY RUN (预览)" if dry_run else "LIVE (真实提交)"
    )
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
    if sku_list:
        print(f"SKU scope: {len(sku_list)} explicit SKUs")
    if sku_file:
        print(f"SKU file: {sku_file}")
    if only_not_on_amazon:
        print("Scope filter: only SKUs not found on Amazon")
    if normalized_engine == "shadow":
        print("Listing payload engine: shadow (V1 behavior + V2 audit)")
    elif normalized_engine == "v2":
        print("Listing payload engine: v2 authoritative dry-run canary")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")

    try:
        service = ProductListingService(db=db)
        service.listing_payload_engine_mode = normalized_engine
        result = service.generate_listings_via_api(
            category_name=category,
            dry_run=dry_run,
            validation_only=strict_validation,
            sku_list=sku_list,
            sku_file=sku_file,
            only_not_on_amazon=only_not_on_amazon,
        )

        print("\n" + "=" * 70)
        if result["success"]:
            print(f"发品API完成: {len(result.get('results', []))} SKUs")
            audit = result.get("audit") or {}
            status_counts = audit.get("result_status_counts") or {}
            if status_counts:
                print("Audit status counts:")
                for status, count in sorted(status_counts.items()):
                    print(f"  {status}: {count}")
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
