"""Unit tests for AmazonOrderSyncService."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.services.amazon_order_sync_service import AmazonOrderSyncService


class FakeOrderRepo:
    def __init__(self, *, pending_count=1, consecutive_failures=1):
        self.sync_run_id = 11
        self.upserts = []
        self.notified = []
        self.finished = []
        self.vendor_map = {"meowSKU1": "GIGA-001"}
        self._pending_count = pending_count
        self._consecutive_failures = consecutive_failures

    def begin_sync_run(self, looked_back_hours):
        self.looked_back_hours = looked_back_hours
        return self.sync_run_id

    def finish_sync_run(self, **kwargs):
        self.finished.append(kwargs)

    def resolve_vendor_skus(self, seller_skus):
        return {sku: self.vendor_map[sku] for sku in seller_skus if sku in self.vendor_map}

    def upsert_order(self, order, items, sync_run_id):
        self.upserts.append({"order": order, "items": items, "sync_run_id": sync_run_id})
        is_new = len(self.upserts) == 1
        return is_new, False

    def count_orders_pending_notification(self):
        return self._pending_count

    def count_consecutive_sync_failures(self, limit=10):
        return self._consecutive_failures

    def get_orders_pending_notification(self):
        return [
            {
                "amazon_order_id": "111-1867131-2920257",
                "order_status": "Unshipped",
                "latest_ship_date": datetime(2026, 6, 14, 6, 59, 59, tzinfo=timezone.utc),
                "shipping_city": "ANAHEIM",
                "shipping_state": "CA",
                "shipping_country": "US",
                "purchase_date": datetime(2026, 6, 10, 1, 0, 0, tzinfo=timezone.utc),
            }
        ]

    def get_order_items(self, amazon_order_id):
        return [
            {
                "seller_sku": "meowSKU1",
                "vendor_sku": "GIGA-001",
                "asin": "B0TEST",
                "title": "Mirror",
                "quantity_ordered": 1,
                "item_price_amount": 610.33,
                "item_price_currency": "USD",
            }
        ]

    def mark_notified(self, amazon_order_id):
        self.notified.append(amazon_order_id)


class FakeOrdersClient:
    def get_orders(self, **kwargs):
        return {
            "body": {
                "payload": {
                    "Orders": [
                        {
                            "AmazonOrderId": "111-1867131-2920257",
                            "OrderStatus": "Unshipped",
                            "FulfillmentChannel": "MFN",
                            "PurchaseDate": "2026-06-10T01:00:00Z",
                            "LatestShipDate": "2026-06-14T06:59:59Z",
                        }
                    ]
                }
            }
        }

    def get_order(self, amazon_order_id):
        return {
            "body": {
                "payload": {
                    "AmazonOrderId": amazon_order_id,
                    "OrderStatus": "Unshipped",
                    "FulfillmentChannel": "MFN",
                    "PurchaseDate": "2026-06-10T01:00:00Z",
                    "LatestShipDate": "2026-06-14T06:59:59Z",
                    "NumberOfItemsUnshipped": 1,
                    "NumberOfItemsShipped": 0,
                    "ShipServiceLevel": "Std US D2D Dom",
                    "SalesChannel": "Amazon.com",
                }
            }
        }

    def get_order_items(self, amazon_order_id):
        return {
            "body": {
                "payload": {
                    "OrderItems": [
                        {
                            "OrderItemId": "item-1",
                            "SellerSKU": "meowSKU1",
                            "ASIN": "B0TEST",
                            "Title": "Mirror",
                            "QuantityOrdered": 1,
                            "QuantityShipped": 0,
                            "ItemPrice": {"CurrencyCode": "USD", "Amount": "610.33"},
                        }
                    ]
                }
            }
        }

    def get_order_address(self, amazon_order_id):
        return {
            "body": {
                "payload": {
                    "AmazonOrderId": amazon_order_id,
                    "ShippingAddress": {
                        "City": "ANAHEIM",
                        "StateOrRegion": "CA",
                        "CountryCode": "US",
                    },
                }
            }
        }


class FakeFeishu:
    def __init__(self, succeed=True, configured=True):
        self.calls = []
        self.succeed = succeed
        self.is_configured = configured

    def send(self, message):
        self.calls.append(
            {
                "title": message.title,
                "content": message.content,
                "severity": message.severity,
                "tags": message.tags,
            }
        )
        return self.succeed


def test_sync_and_notify_persists_order_and_alerts_human(monkeypatch):
    monkeypatch.setenv("AMAZON_ORDER_SYNC_LOOKBACK_HOURS", "24")
    repo = FakeOrderRepo()
    feishu = FakeFeishu()
    service = AmazonOrderSyncService(
        db=MagicMock(),
        orders_client=FakeOrdersClient(),
        order_repo=repo,
        feishu_client=feishu,
    )

    result = service.sync_and_notify(notify=True)

    assert result["fetched_count"] == 1
    assert result["new_count"] == 1
    assert result["notified_count"] == 1
    assert len(repo.upserts) == 1
    assert repo.upserts[0]["items"][0]["vendor_sku"] == "GIGA-001"
    assert repo.notified == ["111-1867131-2920257"]
    assert len(feishu.calls) == 1
    assert "111-1867131-2920257" in feishu.calls[0]["title"]
    assert feishu.calls[0]["tags"] == ["Amazon订单"]
    assert repo.finished[0]["status"] == "success"


def test_sync_and_notify_skips_mark_notified_when_feishu_not_configured(monkeypatch):
    monkeypatch.setenv("AMAZON_ORDER_SYNC_NOTIFY", "true")
    repo = FakeOrderRepo()
    feishu = FakeFeishu(configured=False)
    service = AmazonOrderSyncService(
        db=MagicMock(),
        orders_client=FakeOrdersClient(),
        order_repo=repo,
        feishu_client=feishu,
    )

    result = service.sync_and_notify(notify=True)

    assert result["notified_count"] == 0
    assert repo.notified == []
    assert feishu.calls == []


def test_sync_and_notify_skips_feishu_when_notify_disabled(monkeypatch):
    monkeypatch.setenv("AMAZON_ORDER_SYNC_NOTIFY", "false")
    repo = FakeOrderRepo()
    feishu = FakeFeishu()
    service = AmazonOrderSyncService(
        db=MagicMock(),
        orders_client=FakeOrdersClient(),
        order_repo=repo,
        feishu_client=feishu,
    )

    result = service.sync_and_notify()

    assert result["notified_count"] == 0
    assert feishu.calls == []
    assert repo.notified == []


def test_sync_and_notify_skips_feishu_when_no_pending_orders(monkeypatch):
    monkeypatch.setenv("AMAZON_ORDER_SYNC_NOTIFY", "true")
    repo = FakeOrderRepo(pending_count=0)
    feishu = FakeFeishu()
    service = AmazonOrderSyncService(
        db=MagicMock(),
        orders_client=FakeOrdersClient(),
        order_repo=repo,
        feishu_client=feishu,
    )

    result = service.sync_and_notify(notify=True)

    assert result["notified_count"] == 0
    assert feishu.calls == []
    assert repo.notified == []


def test_sync_failure_sends_feishu_alert(monkeypatch):
    monkeypatch.setenv("AMAZON_ORDER_SYNC_FAILURE_ALERT_THRESHOLD", "3")
    repo = FakeOrderRepo(consecutive_failures=2)
    feishu = FakeFeishu()

    class FailingOrdersClient(FakeOrdersClient):
        def get_orders(self, **kwargs):
            raise RuntimeError("SP-API timeout")

    service = AmazonOrderSyncService(
        db=MagicMock(),
        orders_client=FailingOrdersClient(),
        order_repo=repo,
        feishu_client=feishu,
    )

    with pytest.raises(RuntimeError, match="SP-API timeout"):
        service.sync_and_notify(notify=True)

    assert repo.finished[0]["status"] == "failed"
    assert len(feishu.calls) == 1
    assert feishu.calls[0]["severity"] == "P1"
    assert "SP-API timeout" in feishu.calls[0]["content"]


def test_sync_failure_escalates_to_p0_after_threshold(monkeypatch):
    monkeypatch.setenv("AMAZON_ORDER_SYNC_FAILURE_ALERT_THRESHOLD", "3")
    repo = FakeOrderRepo(consecutive_failures=3)
    feishu = FakeFeishu()

    class FailingOrdersClient(FakeOrdersClient):
        def get_orders(self, **kwargs):
            raise RuntimeError("SP-API timeout")

    service = AmazonOrderSyncService(
        db=MagicMock(),
        orders_client=FailingOrdersClient(),
        order_repo=repo,
        feishu_client=feishu,
    )

    with pytest.raises(RuntimeError):
        service.sync_and_notify(notify=True)

    assert feishu.calls[0]["severity"] == "P0"
    assert "连续失败" in feishu.calls[0]["title"]


def test_build_notification_content_includes_mapping_and_location():
    content = AmazonOrderSyncService._build_notification_content(
        {
            "amazon_order_id": "111-1",
            "order_status": "Unshipped",
            "latest_ship_date": datetime(2026, 6, 14, tzinfo=timezone.utc),
            "shipping_city": "ANAHEIM",
            "shipping_state": "CA",
            "shipping_country": "US",
        },
        [
            {
                "seller_sku": "meowSKU1",
                "vendor_sku": "GIGA-001",
                "asin": "B0TEST",
                "quantity_ordered": 1,
                "item_price_amount": 10.0,
                "item_price_currency": "USD",
            }
        ],
    )

    assert "111-1" in content
    assert "ANAHEIM, CA, US" in content
    assert "meowSKU1" in content
    assert "GIGA-001" in content
