"""Daily Amazon order health report (DB-only, no SP-API calls)."""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from infrastructure.feishu_client import FeishuClient, FeishuMessage
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)

CST = ZoneInfo("Asia/Shanghai")


class AmazonOrderDailyReportService:
    """Builds and sends a 24h order + sync health summary."""

    def __init__(
        self,
        db: Session,
        reporter: Optional[ProgressReporter] = None,
        order_repo: Any = None,
        feishu_client: Any = None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._order_repo_instance = order_repo
        self._feishu_client_instance = feishu_client

    def run_and_notify(self, notify: Optional[bool] = None) -> Dict[str, Any]:
        """Compose the daily report and optionally push it to Feishu."""
        if notify is None:
            notify = os.getenv("AMAZON_ORDER_DAILY_REPORT_NOTIFY", "true").lower() not in {
                "0",
                "false",
                "no",
            }

        hours = int(os.getenv("AMAZON_ORDER_DAILY_REPORT_HOURS", "24"))
        repo = self._order_repo()
        order_stats = repo.get_order_stats_since(hours=hours)
        sync_stats = repo.get_sync_run_stats_since(hours=hours)
        open_stats = repo.get_recent_unshipped_summary(hours=hours)

        now_cst = datetime.now(CST)
        title = f"Amazon 订单日报 — {now_cst.strftime('%Y-%m-%d')}"
        content = self._build_report_content(hours, order_stats, sync_stats, open_stats)
        self.reporter.emit(content.replace("\n", " | ")[:300])

        sent = False
        if notify:
            feishu = self._feishu_client()
            if feishu.is_configured:
                sent = feishu.send(
                    FeishuMessage(
                        title=title,
                        content=content,
                        severity="P2",
                        tags=["订单日报", "健康检查"],
                    )
                )
            else:
                logger.warning("FEISHU_WEBHOOK_URL not configured; daily report logged only")

        return {
            "hours": hours,
            "order_stats": order_stats,
            "sync_stats": sync_stats,
            "open_stats": open_stats,
            "notified": sent,
        }

    def _order_repo(self):
        if self._order_repo_instance is None:
            from src.repositories.amazon_order_repository import AmazonOrderRepository

            self._order_repo_instance = AmazonOrderRepository(self.db)
        return self._order_repo_instance

    def _feishu_client(self):
        if self._feishu_client_instance is None:
            self._feishu_client_instance = FeishuClient.from_env()
        return self._feishu_client_instance

    @staticmethod
    def _build_report_content(
        hours: int,
        order_stats: Dict[str, Any],
        sync_stats: Dict[str, Any],
        open_stats: Dict[str, Any],
    ) -> str:
        lines = [
            f"**统计窗口**: 过去 {hours} 小时（北京时间日报）",
            "",
            "**订单概况**",
            f"- 新进入系统: {order_stats.get('new_orders', 0)} 单",
            f"- 其中待发货/部分发货: {order_stats.get('actionable_orders', 0)} 单",
            f"- 已发货: {order_stats.get('shipped_orders', 0)} 单",
            f"- 已取消: {order_stats.get('canceled_orders', 0)} 单",
            "",
            "**当前待处理**",
            f"- 待发货: {open_stats.get('open_count', 0)} 单",
            f"- 未飞书通知: {open_stats.get('unnotified_count', 0)} 单",
            f"- 已过发货截止: {open_stats.get('overdue_count', 0)} 单",
            "",
            "**同步任务健康**",
            f"- 执行次数: {sync_stats.get('total_runs', 0)}",
            f"- 成功: {sync_stats.get('success_runs', 0)} | "
            f"部分成功: {sync_stats.get('partial_runs', 0)} | "
            f"失败: {sync_stats.get('failed_runs', 0)}",
        ]
        last_error = sync_stats.get("last_error")
        if last_error:
            lines.append(f"- 最近错误: {last_error[:200]}")
        else:
            lines.append("- 最近错误: 无")

        if (
            open_stats.get("overdue_count", 0) == 0
            and sync_stats.get("failed_runs", 0) == 0
            and order_stats.get("new_orders", 0) == 0
        ):
            lines.extend(["", "**结论**: 过去 24h 无新单，同步正常。"])
        elif sync_stats.get("failed_runs", 0) > 0:
            lines.extend(["", "**结论**: 请关注同步失败记录。"])
        else:
            lines.extend(["", "**结论**: 系统运行正常，请按需处理待发货订单。"])
        return "\n".join(lines)
