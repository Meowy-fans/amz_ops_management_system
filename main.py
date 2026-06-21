"""
Amazon Listing Management System - Main Entry Point
主程序入口 - 完整功能版本
"""
import sys
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional
from sqlalchemy.orm import Session
import argparse

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from infrastructure.db_pool import SessionLocal
from src.cli.menu import run_interactive_menu
from src.cli.task_dispatcher import UnknownTaskError, dispatch_task

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
# 减少SQLAlchemy日志输出
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


def _split_sku_args(values):
    skus = []
    for value in values or []:
        for token in str(value).replace(",", "\n").splitlines():
            sku = token.strip()
            if sku:
                skus.append(sku)
    return skus

def main():
    """主程序"""
    load_dotenv()
    logger.info("系统启动")
    
    parser = argparse.ArgumentParser(description="Amazon Listing Management System")
    parser.add_argument("--task", help="任务标识，如: sync-products, generate-listing-api, update-price-inventory-api 等")
    parser.add_argument("--category", help="品类名称，如 CABINET 或 HOME_MIRROR")
    parser.add_argument("--file", help="文件路径，用于需要文件输入的任务")
    parser.add_argument("--auto-confirm", action="store_true", help="自动确认，避免交互式提示")
    parser.add_argument("--no-dry-run", action="store_true", help="禁用 dry-run，真实提交 API 请求")
    parser.add_argument(
        "--strict-validation",
        action="store_true",
        help="API 发品 dry-run 时调用 Amazon VALIDATION_PREVIEW 预检，不执行 PUT",
    )
    parser.add_argument("--sku", action="append", help="限制发品到指定 meow_sku，可重复或逗号分隔")
    parser.add_argument("--sku-file", help="限制发品到文件中的 meow_sku，每行一个，也支持逗号分隔")
    parser.add_argument(
        "--only-not-on-amazon",
        action="store_true",
        help="发品前只读查 Amazon，跳过已存在 SKU",
    )
    parser.add_argument("--category-code", help="供应商品类代码，如 Giga category_code")
    parser.add_argument("--product-type", help="Amazon product type，如 SOFA")
    parser.add_argument(
        "--all-unmapped",
        action="store_true",
        help="处理所有未映射供应商品类",
    )
    args = parser.parse_args()

    non_interactive_task = args.task or os.getenv("APP_TASK")
    param_category = args.category or os.getenv("LISTING_CATEGORY")
    param_file = args.file or os.getenv("INPUT_FILE_PATH")
    auto_confirm = args.auto_confirm or (os.getenv("AUTO_CONFIRM", "false").lower() == "true")
    dry_run = not args.no_dry_run
    strict_validation = args.strict_validation or (
        os.getenv("LISTING_STRICT_VALIDATION", "false").lower() == "true"
    )
    sku_list = _split_sku_args(args.sku) or _split_sku_args([os.getenv("LISTING_SKU", "")])
    param_sku_file = args.sku_file or os.getenv("LISTING_SKU_FILE")
    only_not_on_amazon = args.only_not_on_amazon or (
        os.getenv("LISTING_ONLY_NOT_ON_AMAZON", "false").lower() == "true"
    )
    category_code = args.category_code or os.getenv("SUPPLIER_CATEGORY_CODE")
    product_type = args.product_type or os.getenv("AMAZON_PRODUCT_TYPE")
    all_unmapped = args.all_unmapped or (
        os.getenv("LISTING_ALL_UNMAPPED", "false").lower() == "true"
    )

    if non_interactive_task:
        try:
            with SessionLocal() as db:
                dispatch_task(
                    db,
                    non_interactive_task,
                    category=param_category,
                    file_path=param_file,
                    auto_confirm=auto_confirm,
                    dry_run=dry_run,
                    strict_validation=strict_validation,
                    sku_list=sku_list or None,
                    sku_file=param_sku_file,
                    only_not_on_amazon=only_not_on_amazon,
                    category_code=category_code,
                    all_unmapped=all_unmapped,
                    product_type=product_type,
                )
            sys.exit(0)
        except UnknownTaskError:
            print(f"\n❌ 未知任务: {non_interactive_task}")
            sys.exit(2)
        except KeyboardInterrupt:
            print("\n\n⚠️  程序被用户中断")
            logger.info("系统被用户中断")
            sys.exit(130)
        except Exception as e:
            logger.error(f"发生错误: {e}", exc_info=True)
            print(f"\n❌ 发生错误: {e}")
            sys.exit(1)

    run_interactive_menu(SessionLocal, dispatch_task)


def run_task(
    task: str,
    category: Optional[str] = None,
    file_path: Optional[str] = None,
    auto_confirm: bool = False,
    sku_list: Optional[list[str]] = None,
    sku_file: Optional[str] = None,
    only_not_on_amazon: bool = False,
    category_code: Optional[str] = None,
    all_unmapped: bool = False,
    product_type: Optional[str] = None,
):
    load_dotenv()
    with SessionLocal() as db:
        return dispatch_task(
            db,
            task,
            category=category,
            file_path=file_path,
            auto_confirm=auto_confirm,
            sku_list=sku_list,
            sku_file=sku_file,
            only_not_on_amazon=only_not_on_amazon,
            category_code=category_code,
            all_unmapped=all_unmapped,
            product_type=product_type,
            return_listing_result=True,
        )

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
