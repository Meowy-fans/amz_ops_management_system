"""CLI handlers for Amazon template and category maintenance tasks."""
import csv
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def handle_template_update(
    db: Session,
    template_path: Optional[str] = None,
    category_name: Optional[str] = None,
):
    """3.2 解析新的亚马逊类目模板到数据库"""
    from src.services.amz_template_management_service import TemplateManagementService

    logger.info("🚀 启动更新亚马逊类目模板流程...")
    print("\n" + "=" * 70)
    print("📦 解析新的亚马逊类目模板")
    print("=" * 70)

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
            category_name,
        )

        if success:
            print(f"\n✅ {message}")
        else:
            print(f"\n❌ {message}")

        print("=" * 70)

    except Exception as e:
        print(f"\n❌ 更新亚马逊类目模板时发生错误: {e}")
        logging.exception("详细错误:")


def handle_template_correction(
    db: Session,
    report_path: Optional[str] = None,
    category_name: Optional[str] = None,
):
    """3.3 从亚马逊报错文件自动矫正模板规则"""
    from src.services.amz_template_management_service import TemplateManagementService

    logger.info("🚀 启动模板规则自动矫正流程...")
    print("\n" + "=" * 70)
    print("📦 从报错文件矫正模板规则")
    print("=" * 70)

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
            category_name,
        )

        if success:
            print(f"\n✅ 完成")
        else:
            print(f"\n❌ 失败")

        print("=" * 70)

    except Exception as e:
        print(f"\n❌ 执行模板规则矫正时发生错误: {e}")
        logging.exception("详细错误:")


def handle_sync_giga_categories(
    db: Session,
    auto_confirm: bool = False,
    export: bool = False,
):
    """3.4 更新需要维护的品类(来自Giga)"""
    from src.services.category_maintenance_service import CategoryMaintenanceService

    logger.info("🚀 启动Giga品类同步流程...")
    print("\n" + "=" * 70)
    print("🔄 更新需要维护的品类(来自Giga)")
    print("=" * 70)

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
                if confirm != "y":
                    print("\n❌ 操作已取消")
                    print("=" * 70)
                    return
            else:
                print("❌ 错误: 在 Web 界面运行此任务时，请务必勾选 '自动确认 (Auto Confirm)'")
                print("=" * 70)
                return

        service = CategoryMaintenanceService(db)
        result = service.sync_giga_categories()

        if result.get("inserted_count", 0) > 0:
            print()
            if export:
                export_new_categories(result.get("new_category_list", []))
            elif sys.stdin and sys.stdin.isatty():
                choice = input("是否导出新增品类列表到CSV文件? (y/n): ").strip().lower()
                if choice == "y":
                    export_new_categories(result.get("new_category_list", []))
            else:
                print("⚠️  非交互模式，跳过导出 CSV 询问")

    except Exception as e:
        print(f"\n❌ 品类同步失败: {e}")
        logging.exception("详细错误:")


def export_new_categories(categories: List[Dict]):
    """导出新增品类列表到 CSV 文件"""
    if not categories:
        print("⚠️  没有新品类需要导出")
        return

    project_root = Path(__file__).resolve().parents[2]
    output_dir = os.path.join(project_root, "output")
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"new_giga_categories_{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)

    try:
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["category_code", "category_name", "standard_category_name"],
            )
            writer.writeheader()

            for cat in categories:
                writer.writerow({
                    "category_code": cat["category_code"],
                    "category_name": cat["category_name"],
                    "standard_category_name": "",
                })

        print(f"\n✅ 新品类列表已导出到: {filepath}")
        print("   请在此文件中填写 standard_category_name，然后可以批量导入")

    except Exception as e:
        print(f"❌ 导出失败: {e}")


def handle_update_mappings_from_csv(
    db: Session,
    csv_file_path: Optional[str] = None,
):
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

        service = CategoryMaintenanceService(db)
        result = service.update_mappings_from_csv(csv_file_path)

        print()
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ 批量更新失败: {e}")
        logging.exception("详细错误:")
