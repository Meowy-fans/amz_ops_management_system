"""Amazon order polling, persistence, and human notification."""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from infrastructure.amazon.config import AmazonConfig
from infrastructure.feishu_client import FeishuClient, FeishuMessage
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class AmazonOrderSyncService:
    """Polls Amazon Orders API and notifies humans about new MFN orders."""

    def __init__(
        self,
        db: Session,
        reporter: Optional[ProgressReporter] = None,
        orders_client: Any = None,
        order_repo: Any = None,
        feishu_client: Any = None,
        marketplace_id: Optional[str] = None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._orders_client_instance = orders_client
        self._order_repo_instance = order_repo
        self._feishu_client_instance = feishu_client
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID

    def sync_and_notify(self, notify: Optional[bool] = None) -> Dict[str, Any]:
        """Fetch recent Amazon orders, persist them, and alert humans for new ones."""
        lookback_hours = int(os.getenv("AMAZON_ORDER_SYNC_LOOKBACK_HOURS", "48"))
        if notify is None:
            notify = os.getenv("AMAZON_ORDER_SYNC_NOTIFY", "true").lower() not in {
                "0",
                "false",
                "no",
            }
        statuses = self._parse_csv_env(
            "AMAZON_ORDER_SYNC_STATUSES",
            default=["Unshipped", "PartiallyShipped"],
        )

        repo = self._order_repo()
        sync_run_id = repo.begin_sync_run(lookback_hours)
        fetched_count = 0
        new_count = 0
        changed_count = 0
        notified_count = 0
        errors: List[str] = []

        try:
            orders = self._fetch_orders(lookback_hours, statuses)
            fetched_count = len(orders)
            self.reporter.emit(f"Fetched {fetched_count} Amazon order(s) from API")

            for order_summary in orders:
                amazon_order_id = order_summary.get("AmazonOrderId")
                if not amazon_order_id:
                    continue
                try:
                    is_new, status_changed = self._persist_order(
                        repo, sync_run_id, order_summary
                    )
                    if is_new:
                        new_count += 1
                        changed_count += 1
                    elif status_changed:
                        changed_count += 1
                except Exception as exc:
                    message = f"{amazon_order_id}: {exc}"
                    errors.append(message)
                    logger.warning(
                        "Failed to persist Amazon order %s: %s", amazon_order_id, exc
                    )

            if notify:
                pending_count = repo.count_orders_pending_notification()
                if pending_count == 0:
                    self.reporter.emit(
                        "No notifyable order changes; skipping Feishu order alerts"
                    )
                else:
                    if new_count == 0 and changed_count == 0:
                        self.reporter.emit(
                            f"Retrying Feishu alerts for {pending_count} pending order(s)"
                        )
                    notified_count = self._notify_pending_orders(repo)

            status = "partial_success" if errors else "success"
            repo.finish_sync_run(
                sync_run_id=sync_run_id,
                status=status,
                fetched_count=fetched_count,
                new_count=new_count,
                notified_count=notified_count,
                error_message="; ".join(errors[:5]) if errors else None,
            )
            if errors:
                self._notify_partial_errors(errors)

            self._emit_summary(
                fetched_count, new_count, changed_count, notified_count, notify, errors
            )
            return {
                "sync_run_id": sync_run_id,
                "fetched_count": fetched_count,
                "new_count": new_count,
                "changed_count": changed_count,
                "notified_count": notified_count,
                "error_count": len(errors),
                "notify": notify,
            }
        except Exception as exc:
            repo.finish_sync_run(
                sync_run_id=sync_run_id,
                status="failed",
                fetched_count=fetched_count,
                new_count=new_count,
                notified_count=notified_count,
                error_message=str(exc),
            )
            self._notify_sync_failure(repo, exc)
            raise

    def _orders_client(self):
        if self._orders_client_instance is None:
            from infrastructure.amazon.orders_client import AmazonOrdersClient

            self._orders_client_instance = AmazonOrdersClient()
        return self._orders_client_instance

    def _order_repo(self):
        if self._order_repo_instance is None:
            from src.repositories.amazon_order_repository import AmazonOrderRepository

            self._order_repo_instance = AmazonOrderRepository(self.db)
        return self._order_repo_instance

    def _feishu_client(self):
        if self._feishu_client_instance is None:
            self._feishu_client_instance = FeishuClient.from_env()
        return self._feishu_client_instance

    def _fetch_orders(
        self,
        lookback_hours: int,
        statuses: List[str],
    ) -> List[Dict[str, Any]]:
        created_after = (
            datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        orders: List[Dict[str, Any]] = []
        next_token: Optional[str] = None

        while True:
            response = self._orders_client().get_orders(
                created_after=created_after,
                order_statuses=statuses,
                fulfillment_channels=["MFN"],
                next_token=next_token,
            )
            payload = (response.get("body") or {}).get("payload") or {}
            orders.extend(payload.get("Orders") or [])
            next_token = payload.get("NextToken")
            if not next_token:
                break
        return orders

    def _persist_order(
        self,
        repo: Any,
        sync_run_id: int,
        order_summary: Dict[str, Any],
    ) -> tuple:
        amazon_order_id = order_summary["AmazonOrderId"]
        detail_resp = self._orders_client().get_order(amazon_order_id)
        detail = (detail_resp.get("body") or {}).get("payload") or order_summary

        items_resp = self._orders_client().get_order_items(amazon_order_id)
        raw_items = ((items_resp.get("body") or {}).get("payload") or {}).get(
            "OrderItems"
        ) or []

        address_resp = self._orders_client().get_order_address(amazon_order_id)
        address_payload = (address_resp.get("body") or {}).get("payload") or {}
        shipping_address = address_payload.get("ShippingAddress") or {}

        seller_skus = [
            item.get("SellerSKU")
            for item in raw_items
            if item.get("SellerSKU")
        ]
        vendor_map = repo.resolve_vendor_skus(seller_skus)

        order_row = {
            "amazon_order_id": amazon_order_id,
            "marketplace_id": self.marketplace_id,
            "order_status": detail.get("OrderStatus") or order_summary.get("OrderStatus"),
            "fulfillment_channel": detail.get("FulfillmentChannel")
            or order_summary.get("FulfillmentChannel"),
            "purchase_date": self._parse_datetime(
                detail.get("PurchaseDate") or order_summary.get("PurchaseDate")
            ),
            "latest_ship_date": self._parse_datetime(
                detail.get("LatestShipDate") or order_summary.get("LatestShipDate")
            ),
            "number_of_items_unshipped": int(
                detail.get("NumberOfItemsUnshipped")
                or order_summary.get("NumberOfItemsUnshipped")
                or 0
            ),
            "number_of_items_shipped": int(
                detail.get("NumberOfItemsShipped")
                or order_summary.get("NumberOfItemsShipped")
                or 0
            ),
            "ship_service_level": detail.get("ShipServiceLevel")
            or order_summary.get("ShipServiceLevel"),
            "sales_channel": detail.get("SalesChannel") or order_summary.get("SalesChannel"),
            "shipping_city": shipping_address.get("City"),
            "shipping_state": shipping_address.get("StateOrRegion"),
            "shipping_country": shipping_address.get("CountryCode"),
            "raw_order": detail,
            "raw_address": address_payload,
        }

        item_rows = []
        for raw_item in raw_items:
            seller_sku = raw_item.get("SellerSKU")
            item_price = raw_item.get("ItemPrice") or {}
            item_rows.append(
                {
                    "amazon_order_id": amazon_order_id,
                    "order_item_id": raw_item.get("OrderItemId"),
                    "seller_sku": seller_sku,
                    "asin": raw_item.get("ASIN"),
                    "title": raw_item.get("Title"),
                    "quantity_ordered": int(raw_item.get("QuantityOrdered") or 0),
                    "quantity_shipped": int(raw_item.get("QuantityShipped") or 0),
                    "item_price_amount": self._parse_amount(item_price.get("Amount")),
                    "item_price_currency": item_price.get("CurrencyCode"),
                    "vendor_sku": vendor_map.get(seller_sku),
                    "raw_item": raw_item,
                }
            )

        return repo.upsert_order(order_row, item_rows, sync_run_id)

    def _notify_pending_orders(self, repo: Any) -> int:
        pending = repo.get_orders_pending_notification()
        notified = 0
        feishu = self._feishu_client()

        if not feishu.is_configured:
            logger.warning(
                "FEISHU_WEBHOOK_URL is not configured; skipping order alerts "
                "(orders remain in DB with notified_at=NULL)"
            )
            self.reporter.emit(
                f"Feishu webhook not configured; {len(pending)} order(s) pending notification"
            )
            return 0

        for order in pending:
            amazon_order_id = order["amazon_order_id"]
            items = repo.get_order_items(amazon_order_id)
            content = self._build_notification_content(order, items)
            title = f"Amazon 新订单待处理 — {amazon_order_id}"
            if feishu.send(
                FeishuMessage(
                    title=title,
                    content=content,
                    severity="P1",
                    tags=["Amazon订单"],
                )
            ):
                repo.mark_notified(amazon_order_id)
                notified += 1
                self.reporter.emit(f"Feishu alert sent for order {amazon_order_id}")
            else:
                logger.warning("Feishu notification failed for order %s", amazon_order_id)
        return notified

    def _notify_sync_failure(self, repo: Any, exc: Exception) -> None:
        feishu = self._feishu_client()
        if not feishu.is_configured:
            return

        threshold = int(os.getenv("AMAZON_ORDER_SYNC_FAILURE_ALERT_THRESHOLD", "3"))
        consecutive = repo.count_consecutive_sync_failures(limit=threshold)
        severity = "P0" if consecutive >= threshold else "P1"
        title = (
            f"Amazon 订单同步连续失败 {consecutive} 次"
            if consecutive >= threshold
            else "Amazon 订单同步失败"
        )
        content = (
            f"**错误**: {exc}\n\n"
            f"**连续失败次数**: {consecutive}\n\n"
            "请检查 Amazon SP-API 凭证、堡垒机代理与网络连通性。"
        )
        feishu.send(
            FeishuMessage(
                title=title,
                content=content,
                severity=severity,
                tags=["Amazon订单", "同步异常"],
            )
        )

    def _notify_partial_errors(self, errors: List[str]) -> None:
        feishu = self._feishu_client()
        if not feishu.is_configured or not errors:
            return

        feishu.send(
            FeishuMessage(
                title="Amazon 订单同步部分失败",
                content=(
                    f"共 {len(errors)} 个订单落库失败：\n"
                    + "\n".join(f"- {err}" for err in errors[:5])
                ),
                severity="P2",
                tags=["Amazon订单", "同步异常"],
            )
        )

    @staticmethod
    def _build_notification_content(
        order: Dict[str, Any],
        items: List[Dict[str, Any]],
    ) -> str:
        ship_by = order.get("latest_ship_date")
        ship_by_text = ship_by.strftime("%Y-%m-%d %H:%M UTC") if ship_by else "未知"
        location_parts = [
            part
            for part in [
                order.get("shipping_city"),
                order.get("shipping_state"),
                order.get("shipping_country"),
            ]
            if part
        ]
        location = ", ".join(location_parts) or "地址未返回（需后续申请 PII 权限）"

        lines = [
            f"**订单号**: {order['amazon_order_id']}",
            f"**状态**: {order['order_status']}",
            f"**发货截止**: {ship_by_text}",
            f"**收货地**: {location}",
            "",
            "**商品**:",
        ]
        if not items:
            lines.append("- （无行项目）")
        else:
            for item in items:
                seller_sku = item.get("seller_sku") or "-"
                vendor_sku = item.get("vendor_sku") or "未映射"
                qty = item.get("quantity_ordered") or 0
                price = item.get("item_price_amount")
                currency = item.get("item_price_currency") or "USD"
                price_text = f"{currency} {price}" if price is not None else "-"
                lines.append(
                    f"- `{seller_sku}` → `{vendor_sku}` | "
                    f"{item.get('asin') or '-'} | x{qty} | {price_text}"
                )
        lines.extend(
            [
                "",
                "请在 Giga 后台手动下单；完整街道地址待 Amazon PII 权限开通后自动补齐。",
            ]
        )
        return "\n".join(lines)

    def _emit_summary(
        self,
        fetched_count: int,
        new_count: int,
        changed_count: int,
        notified_count: int,
        notify: bool,
        errors: List[str],
    ) -> None:
        self.reporter.emit(
            "Amazon order sync complete: "
            f"fetched={fetched_count}, new={new_count}, changed={changed_count}, "
            f"notified={notified_count}, notify_enabled={notify}"
        )
        if errors:
            self.reporter.emit(f"Errors: {'; '.join(errors[:3])}")

    @staticmethod
    def _parse_csv_env(name: str, default: List[str]) -> List[str]:
        raw = os.getenv(name, "")
        if not raw.strip():
            return default
        return [part.strip() for part in raw.split(",") if part.strip()]

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)

    @staticmethod
    def _parse_amount(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        return float(value)
