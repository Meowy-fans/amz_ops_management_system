"""Daily health-check orchestration.

Runs at a configured time each day, gathers status from all subsystems,
compiles a structured report, and pushes alerts via Feishu.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── output model ────────────────────────────────────────────────────


@dataclass
class DailyCheckResult:
    check_time: str = ""
    overall_status: str = "OK"  # OK, WARNING, CRITICAL
    sections: Dict[str, str] = field(default_factory=dict)
    alerts: List[Dict[str, str]] = field(default_factory=list)


# ── service ─────────────────────────────────────────────────────────


class DailyCheckService:
    """Collects health signals from all subsystems and produces a daily report.

    Each check_* method:
      - returns a (status, summary, alerts) tuple
      - status is one of: OK, WARNING, CRITICAL
      - gracefully degrades when its data source is unavailable
    """

    def __init__(self, db: Session):
        self.db = db
        self._now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def run(self) -> DailyCheckResult:
        """Execute all checks and aggregate into one report."""
        result = DailyCheckResult(check_time=self._now)

        sections = []
        all_alerts = []

        for check_fn in [
            self._check_listing_issues,
            self._check_recent_orders,
            self._check_inventory_alerts,
        ]:
            try:
                status, summary, alerts = check_fn()
                sections.append(summary)
                all_alerts.extend(alerts)
                if status == "CRITICAL" and result.overall_status != "CRITICAL":
                    result.overall_status = "CRITICAL"
                elif status == "WARNING" and result.overall_status == "OK":
                    result.overall_status = "WARNING"
            except Exception as exc:
                logger.error("Daily check %s failed: %s", check_fn.__name__, exc)
                sections.append(f"**{check_fn.__name__}**: 检查失败 ({exc})")
                all_alerts.append({
                    "title": f"巡检异常: {check_fn.__name__}",
                    "content": str(exc),
                    "severity": "P1",
                })

        result.sections = {
            "巡检时间": self._now,
            "整体状态": result.overall_status,
            "各模块详情": "\n\n".join(sections) if sections else "所有检查通过",
        }
        result.alerts = all_alerts
        return result

    # ── individual checks ───────────────────────────────────────────

    def _check_listing_issues(self) -> tuple:
        """Check for unresolved listing issues from existing data."""
        try:
            from src.repositories.amazon_listing_issue_repository import (
                AmazonListingIssueRepository,
            )

            repo = AmazonListingIssueRepository(self.db)
            open_issues = repo.get_open_issues()

            if not open_issues:
                return ("OK", "**Listing问题**: 0 个待处理", [])

            total = len(open_issues)
            critical_issues = [i for i in open_issues if i.get("severity") == "ERROR"]
            critical_count = len(critical_issues)
            warning_count = total - critical_count

            alerts = []
            if critical_count > 0:
                top_critical = critical_issues[:3]
                detail_lines = []
                for item in top_critical:
                    sku = item.get("sku") or "-"
                    msg = (item.get("message") or "")[:80]
                    detail_lines.append(f"  • {sku}: {msg}")
                detail_text = "\n".join(detail_lines)
                alerts.append({
                    "title": f"{critical_count} 个严重Listing问题",
                    "content": (
                        f"总计 {total} 个待处理（严重: {critical_count}, 警告: {warning_count}）\n"
                        f"---\n{detail_text}"
                    ),
                    "severity": "P1",
                })

            status = "CRITICAL" if critical_count > 0 else "WARNING"
            summary = (
                f"**Listing问题**: {total} 个待处理（严重: {critical_count}, 警告: {warning_count}）"
            )
            return (status, summary, alerts)
        except Exception:
            return ("OK", "**Listing问题**: 检查暂不可用", [])

    def _check_recent_orders(self) -> tuple:
        """Check persisted Amazon orders for open or overdue MFN shipments."""
        try:
            from src.repositories.amazon_order_repository import AmazonOrderRepository

            summary = AmazonOrderRepository(self.db).get_recent_unshipped_summary(hours=72)
            open_count = int(summary.get("open_count") or 0)
            unnotified_count = int(summary.get("unnotified_count") or 0)
            overdue_count = int(summary.get("overdue_count") or 0)

            if open_count == 0:
                return ("OK", "**订单状态**: 近 72h 无待发货 MFN 订单", [])

            summary_text = (
                f"**订单状态**: 待发货 {open_count} 单"
                f"（未通知 {unnotified_count}，已逾期 {overdue_count}）"
            )
            alerts = []
            if unnotified_count > 0 or overdue_count > 0:
                status = "CRITICAL" if overdue_count > 0 else "WARNING"
                detail_parts = []
                if unnotified_count > 0:
                    detail_parts.append(f"未通知 {unnotified_count} 单")
                if overdue_count > 0:
                    detail_parts.append(f"已过发货截止 {overdue_count} 单")
                alerts.append({
                    "title": "Amazon 订单待人工处理",
                    "content": (
                        f"近 72h 待发货订单 {open_count} 单；"
                        + "，".join(detail_parts)
                        + "。请运行 sync-amazon-orders 或到 Giga 后台处理。"
                    ),
                    "severity": "P1" if overdue_count > 0 else "P2",
                })
                return (status, summary_text, alerts)
            return ("OK", summary_text, [])
        except Exception:
            return ("OK", "**订单状态**: 检测暂不可用（请先执行 migration 009）", [])

    def _check_inventory_alerts(self) -> tuple:
        """Check for low-inventory products (reuses existing data)."""
        try:
            from src.repositories.giga_product_inventory_repository import (
                GigaProductInventoryRepository,
            )

            repo = GigaProductInventoryRepository(self.db)
            stats = repo.get_statistics()

            total = stats.get("total_skus", 0)
            in_stock = stats.get("in_stock", 0)
            total_qty = stats.get("total_quantity", 0)

            summary = (
                f"**库存概况**: {total} SKU总数, {in_stock} 有库存, "
                f"总库存量 {total_qty} 件"
            )

            if total > 0 and in_stock < total * 0.7:
                return (
                    "WARNING",
                    summary + f"\n⚠️ {(total - in_stock)} 个SKU零库存",
                    [{
                        "title": f"{(total - in_stock)} 个SKU零库存",
                        "content": f"共 {total} 个SKU中 {total - in_stock} 个库存为0",
                        "severity": "P2",
                    }],
                )
            return ("OK", summary, [])
        except Exception:
            return ("OK", "**库存预警**: 数据暂不可用", [])


# ── standalone runner ───────────────────────────────────────────────


def run_daily_check(db: Session, notify: bool = True) -> DailyCheckResult:
    """Entry point for daily check task (CLI / scheduler).

    Args:
        db: Database session.
        notify: When True, push alerts to Feishu.

    Returns:
        The compiled DailyCheckResult.
    """
    service = DailyCheckService(db)
    result = service.run()

    logger.info(
        "Daily check complete — status=%s, alerts=%d",
        result.overall_status,
        len(result.alerts),
    )

    if notify and result.alerts:
        from infrastructure.feishu_client import FeishuClient

        feishu = FeishuClient.from_env()
        for alert in result.alerts:
            feishu.send_alert(
                title=alert["title"],
                content=alert["content"],
                severity=alert.get("severity", "P1"),
            )

        sections = {}
        for k, v in result.sections.items():
            sections[k] = v
        feishu.send_daily_report(
            title=f"每日巡检报告 — {result.check_time}",
            sections=sections,
        )

    return result
