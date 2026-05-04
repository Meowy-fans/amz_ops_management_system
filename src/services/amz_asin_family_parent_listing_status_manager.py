"""
Amazon Listing Status Manager Service
亚马逊发品状态管理服务

负责将'GENERATED'状态的发品日志，根据亚马逊在售报告，更新为'LISTED'
"""
from sqlalchemy.orm import Session
from src.repositories.amz_listing_log_repository import AmzListingLogRepository
from src.services.progress_reporter import ProgressReporter
import logging

logger = logging.getLogger(__name__)


class ListingStatusManager:
    """
    服务层，负责将'GENERATED'状态的发品日志，根据亚马逊在售报告，更新为'LISTED'。
    """

    def __init__(self, db: Session, reporter: ProgressReporter | None = None):
        """
        构造函数，接收数据库会话。
        
        Args:
            db: SQLAlchemy Session 对象
        """
        self.db = db
        self.log_repo = AmzListingLogRepository(db=self.db)
        self.reporter = reporter or ProgressReporter()

    def update_statuses_to_listed(self):
        """
        核心业务逻辑：触发批量状态更新，并报告结果。
        """
        self.reporter.emit("\n➡️ 正在根据亚马逊在售报告，更新发品日志状态...")
        logger.info("开始执行发品日志状态批量更新...")

        try:
            updated_count = self.log_repo.bulk_update_status_to_listed()

            if updated_count > 0:
                success_message = f"✔️ 状态更新成功！共 {updated_count} 个SKU的发品状态已从 'GENERATED' 更新为 'LISTED'。"
                self.reporter.emit(success_message)
                logger.info(success_message)
            elif updated_count == 0:
                zero_message = "ℹ️ 本次运行没有找到需要更新状态的SKU。"
                self.reporter.emit(zero_message)
                logger.info(zero_message)
            else:  # updated_count is -1
                error_message = "❌ 状态更新过程中发生数据库错误，操作已回滚。请检查日志获取详细信息。"
                self.reporter.emit(error_message)
                logger.error(error_message)

            self.db.commit()  # 如果没有错误，提交事务

        except Exception as e:
            error_message = f"执行状态更新时发生未知严重错误: {e}"
            self.reporter.emit(f"\n❌ {error_message}")
            logger.exception(error_message)
            self.db.rollback()
