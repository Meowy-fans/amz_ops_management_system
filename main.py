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
                dispatch_task(
                    db,
                    non_interactive_task,
                    category=param_category,
                    file_path=param_file,
                    auto_confirm=auto_confirm,
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


def run_task(task: str, category: Optional[str] = None, file_path: Optional[str] = None, auto_confirm: bool = False):
    load_dotenv()
    with SessionLocal() as db:
        return dispatch_task(
            db,
            task,
            category=category,
            file_path=file_path,
            auto_confirm=auto_confirm,
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
