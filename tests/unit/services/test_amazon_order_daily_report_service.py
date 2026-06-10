"""Unit tests for AmazonOrderDailyReportService."""
from unittest.mock import MagicMock

from src.services.amazon_order_daily_report_service import AmazonOrderDailyReportService


class FakeDailyReportRepo:
    def get_order_stats_since(self, hours):
        return {
            "new_orders": 0,
            "actionable_orders": 0,
            "shipped_orders": 0,
            "canceled_orders": 0,
        }

    def get_sync_run_stats_since(self, hours):
        return {
            "total_runs": 48,
            "success_runs": 48,
            "partial_runs": 0,
            "failed_runs": 0,
            "last_error": None,
        }

    def get_recent_unshipped_summary(self, hours):
        return {
            "open_count": 0,
            "unnotified_count": 0,
            "overdue_count": 0,
        }


class FakeFeishu:
    def __init__(self, configured=True):
        self.is_configured = configured
        self.calls = []

    def send(self, message):
        self.calls.append(
            {
                "title": message.title,
                "content": message.content,
                "severity": message.severity,
                "tags": message.tags,
            }
        )
        return True


def test_daily_report_sends_feishu_summary(monkeypatch):
    monkeypatch.setenv("AMAZON_ORDER_DAILY_REPORT_NOTIFY", "true")
    monkeypatch.setenv("AMAZON_ORDER_DAILY_REPORT_HOURS", "24")
    feishu = FakeFeishu()
    service = AmazonOrderDailyReportService(
        db=MagicMock(),
        order_repo=FakeDailyReportRepo(),
        feishu_client=feishu,
    )

    result = service.run_and_notify()

    assert result["hours"] == 24
    assert result["notified"] is True
    assert len(feishu.calls) == 1
    assert feishu.calls[0]["tags"] == ["订单日报", "健康检查"]
    assert "过去 24 小时" in feishu.calls[0]["content"]
    assert "无新单" in feishu.calls[0]["content"]


def test_daily_report_skips_feishu_when_not_configured(monkeypatch):
    monkeypatch.setenv("AMAZON_ORDER_DAILY_REPORT_NOTIFY", "true")
    feishu = FakeFeishu(configured=False)
    service = AmazonOrderDailyReportService(
        db=MagicMock(),
        order_repo=FakeDailyReportRepo(),
        feishu_client=feishu,
    )

    result = service.run_and_notify()

    assert result["notified"] is False
    assert feishu.calls == []
