"""Interactive CLI menu shell."""
import logging
from typing import Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


INTERACTIVE_TASK_CHOICES = {
    "1.1": "sync-products",
    "1.2": "import-amz-report",
    "1.3": "update-listing-status",
    "1.4": "generate-details",
    "1.5": "sync-prices",
    "1.6": "sync-inventory",
    "1.7": "update-prices",
    "1.8": "generate-listing",
    "2.1": "view-statistics",
    "2.2": "pending-statistics",
    "2.3": "recent-listings",
    "3.1": "list-categories",
    "3.2": "template-update",
    "3.3": "template-correction",
    "3.4": "sync-giga-categories",
    "3.5": "update-mappings-from-csv",
    "4.1": "sku-sync-from-csv",
    "5.1": "generate-update-file",
}


def print_header():
    """Print the system title."""
    print("\n" + "=" * 70)
    print("🚀 Amazon Listing Management System")
    print("   电商自动化运营系统")
    print("=" * 70)


def print_menu():
    """Print the main menu."""
    print("\n" + "-" * 70)
    print("📋 主菜单")
    print("-" * 70)
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
    print("-" * 70)


def run_interactive_menu(
    session_factory: Callable[[], Session],
    dispatch_task: Callable[[Session, str], object],
):
    """Run the legacy interactive menu loop."""
    while True:
        try:
            print_header()
            print_menu()
            choice = input("\n请输入功能编号: ").strip()
            if choice == "0":
                print("\n👋 感谢使用！再见！\n")
                logger.info("系统退出")
                break
            task = INTERACTIVE_TASK_CHOICES.get(choice)
            if task is None:
                print("\n❌ 无效的选项，请重新输入")
                input("\n按回车键继续...")
                continue
            with session_factory() as db:
                dispatch_task(db, task)
            input("\n按回车键继续...")
        except KeyboardInterrupt:
            print("\n\n⚠️  程序被用户中断")
            logger.info("系统被用户中断")
            break
        except Exception as e:
            logger.error(f"发生错误: {e}", exc_info=True)
            print(f"\n❌ 发生错误: {e}")
            input("\n按回车键继续...")
