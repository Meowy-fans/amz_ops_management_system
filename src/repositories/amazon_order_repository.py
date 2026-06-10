"""Repository for Amazon order sync records."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


class AmazonOrderRepository:
    """Data access for Amazon order sync runs and persisted orders."""

    def __init__(self, db: Session):
        self.db = db

    def begin_sync_run(self, looked_back_hours: int) -> int:
        result = self.db.execute(
            text("""
                INSERT INTO amazon_order_sync_runs (status, looked_back_hours, started_at)
                VALUES ('running', :looked_back_hours, :started_at)
                RETURNING id
            """),
            {
                "looked_back_hours": looked_back_hours,
                "started_at": datetime.now(timezone.utc),
            },
        )
        self.db.commit()
        return result.scalar_one()

    def finish_sync_run(
        self,
        sync_run_id: int,
        status: str,
        fetched_count: int,
        new_count: int,
        notified_count: int,
        error_message: Optional[str] = None,
    ) -> None:
        self.db.execute(
            text("""
                UPDATE amazon_order_sync_runs
                SET status = :status,
                    fetched_count = :fetched_count,
                    new_count = :new_count,
                    notified_count = :notified_count,
                    error_message = :error_message,
                    finished_at = :finished_at
                WHERE id = :id
            """),
            {
                "id": sync_run_id,
                "status": status,
                "fetched_count": fetched_count,
                "new_count": new_count,
                "notified_count": notified_count,
                "error_message": error_message,
                "finished_at": datetime.now(timezone.utc),
            },
        )
        self.db.commit()

    def resolve_vendor_skus(self, seller_skus: List[str]) -> Dict[str, str]:
        if not seller_skus:
            return {}
        rows = self.db.execute(
            text("""
                SELECT meow_sku, vendor_sku
                FROM meow_sku_map
                WHERE meow_sku IN :skus
            """).bindparams(bindparam("skus", expanding=True)),
            {"skus": seller_skus},
        ).fetchall()
        return {row.meow_sku: row.vendor_sku for row in rows}

    def upsert_order(
        self,
        order: Dict[str, Any],
        items: List[Dict[str, Any]],
        sync_run_id: int,
    ) -> bool:
        """Persist an order and its items. Returns True when the order is newly created."""
        now = datetime.now(timezone.utc)
        existing = self.db.execute(
            text("""
                SELECT id, order_status
                FROM amazon_orders
                WHERE amazon_order_id = :amazon_order_id
            """),
            {"amazon_order_id": order["amazon_order_id"]},
        ).fetchone()
        is_new = existing is None
        status_changed = (
            not is_new
            and existing.order_status != order["order_status"]
        )

        self.db.execute(
            text("""
                INSERT INTO amazon_orders (
                    amazon_order_id, marketplace_id, order_status, fulfillment_channel,
                    purchase_date, latest_ship_date, number_of_items_unshipped,
                    number_of_items_shipped, ship_service_level, sales_channel,
                    shipping_city, shipping_state, shipping_country,
                    raw_order, raw_address, sync_run_id, first_seen_at, last_seen_at
                ) VALUES (
                    :amazon_order_id, :marketplace_id, :order_status, :fulfillment_channel,
                    :purchase_date, :latest_ship_date, :number_of_items_unshipped,
                    :number_of_items_shipped, :ship_service_level, :sales_channel,
                    :shipping_city, :shipping_state, :shipping_country,
                    :raw_order, :raw_address, :sync_run_id, :now, :now
                )
                ON CONFLICT (amazon_order_id) DO UPDATE SET
                    order_status = EXCLUDED.order_status,
                    fulfillment_channel = EXCLUDED.fulfillment_channel,
                    purchase_date = EXCLUDED.purchase_date,
                    latest_ship_date = EXCLUDED.latest_ship_date,
                    number_of_items_unshipped = EXCLUDED.number_of_items_unshipped,
                    number_of_items_shipped = EXCLUDED.number_of_items_shipped,
                    ship_service_level = EXCLUDED.ship_service_level,
                    sales_channel = EXCLUDED.sales_channel,
                    shipping_city = EXCLUDED.shipping_city,
                    shipping_state = EXCLUDED.shipping_state,
                    shipping_country = EXCLUDED.shipping_country,
                    raw_order = EXCLUDED.raw_order,
                    raw_address = EXCLUDED.raw_address,
                    sync_run_id = EXCLUDED.sync_run_id,
                    last_seen_at = EXCLUDED.last_seen_at
            """),
            {
                **order,
                "raw_order": json.dumps(order.get("raw_order") or {}),
                "raw_address": json.dumps(order.get("raw_address") or {}),
                "sync_run_id": sync_run_id,
                "now": now,
            },
        )

        for item in items:
            self.db.execute(
                text("""
                    INSERT INTO amazon_order_items (
                        amazon_order_id, order_item_id, seller_sku, asin, title,
                        quantity_ordered, quantity_shipped, item_price_amount,
                        item_price_currency, vendor_sku, raw_item
                    ) VALUES (
                        :amazon_order_id, :order_item_id, :seller_sku, :asin, :title,
                        :quantity_ordered, :quantity_shipped, :item_price_amount,
                        :item_price_currency, :vendor_sku, :raw_item
                    )
                    ON CONFLICT (amazon_order_id, order_item_id) DO UPDATE SET
                        seller_sku = EXCLUDED.seller_sku,
                        asin = EXCLUDED.asin,
                        title = EXCLUDED.title,
                        quantity_ordered = EXCLUDED.quantity_ordered,
                        quantity_shipped = EXCLUDED.quantity_shipped,
                        item_price_amount = EXCLUDED.item_price_amount,
                        item_price_currency = EXCLUDED.item_price_currency,
                        vendor_sku = EXCLUDED.vendor_sku,
                        raw_item = EXCLUDED.raw_item
                """),
                {
                    **item,
                    "raw_item": json.dumps(item.get("raw_item") or {}),
                },
            )

        self.db.commit()
        return is_new, status_changed

    def count_orders_pending_notification(self) -> int:
        row = self.db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM amazon_orders
                WHERE notified_at IS NULL
                  AND order_status IN ('Unshipped', 'PartiallyShipped')
            """)
        ).fetchone()
        return int(row.cnt if row else 0)

    def get_recent_sync_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self.db.execute(
            text("""
                SELECT id, status, started_at, finished_at, fetched_count,
                       new_count, notified_count, error_message
                FROM amazon_order_sync_runs
                ORDER BY started_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()
        return [dict(row._mapping) for row in rows]

    def count_consecutive_sync_failures(self, limit: int = 10) -> int:
        runs = self.get_recent_sync_runs(limit=limit)
        count = 0
        for run in runs:
            if run.get("status") == "failed":
                count += 1
            else:
                break
        return count

    def get_order_stats_since(self, hours: int = 24) -> Dict[str, Any]:
        row = self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS new_orders,
                    COUNT(*) FILTER (
                        WHERE order_status IN ('Unshipped', 'PartiallyShipped')
                    ) AS actionable_orders,
                    COUNT(*) FILTER (
                        WHERE order_status = 'Shipped'
                    ) AS shipped_orders,
                    COUNT(*) FILTER (
                        WHERE order_status = 'Canceled'
                    ) AS canceled_orders
                FROM amazon_orders
                WHERE first_seen_at >= NOW() - make_interval(hours => :hours)
            """),
            {"hours": hours},
        ).fetchone()
        return dict(row._mapping) if row else {
            "new_orders": 0,
            "actionable_orders": 0,
            "shipped_orders": 0,
            "canceled_orders": 0,
        }

    def get_sync_run_stats_since(self, hours: int = 24) -> Dict[str, Any]:
        row = self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_runs,
                    COUNT(*) FILTER (WHERE status = 'success') AS success_runs,
                    COUNT(*) FILTER (WHERE status = 'partial_success') AS partial_runs,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_runs
                FROM amazon_order_sync_runs
                WHERE started_at >= NOW() - make_interval(hours => :hours)
            """),
            {"hours": hours},
        ).fetchone()
        stats = dict(row._mapping) if row else {
            "total_runs": 0,
            "success_runs": 0,
            "partial_runs": 0,
            "failed_runs": 0,
        }
        last_error_row = self.db.execute(
            text("""
                SELECT error_message
                FROM amazon_order_sync_runs
                WHERE started_at >= NOW() - make_interval(hours => :hours)
                  AND error_message IS NOT NULL
                  AND btrim(error_message) <> ''
                ORDER BY started_at DESC
                LIMIT 1
            """),
            {"hours": hours},
        ).fetchone()
        stats["last_error"] = last_error_row.error_message if last_error_row else None
        return stats

    def mark_notified(self, amazon_order_id: str) -> None:
        self.db.execute(
            text("""
                UPDATE amazon_orders
                SET notified_at = :notified_at
                WHERE amazon_order_id = :amazon_order_id
            """),
            {
                "amazon_order_id": amazon_order_id,
                "notified_at": datetime.now(timezone.utc),
            },
        )
        self.db.commit()

    def get_orders_pending_notification(self) -> List[Dict[str, Any]]:
        rows = self.db.execute(
            text("""
                SELECT
                    o.amazon_order_id,
                    o.order_status,
                    o.latest_ship_date,
                    o.shipping_city,
                    o.shipping_state,
                    o.shipping_country,
                    o.purchase_date
                FROM amazon_orders o
                WHERE o.notified_at IS NULL
                  AND o.order_status IN ('Unshipped', 'PartiallyShipped')
                ORDER BY o.latest_ship_date NULLS LAST, o.purchase_date
            """)
        ).fetchall()
        return [dict(row._mapping) for row in rows]

    def get_order_items(self, amazon_order_id: str) -> List[Dict[str, Any]]:
        rows = self.db.execute(
            text("""
                SELECT seller_sku, vendor_sku, asin, title,
                       quantity_ordered, item_price_amount, item_price_currency
                FROM amazon_order_items
                WHERE amazon_order_id = :amazon_order_id
                ORDER BY id
            """),
            {"amazon_order_id": amazon_order_id},
        ).fetchall()
        return [dict(row._mapping) for row in rows]

    def get_recent_unshipped_summary(self, hours: int = 72) -> Dict[str, Any]:
        row = self.db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (
                        WHERE order_status IN ('Unshipped', 'PartiallyShipped')
                    ) AS open_count,
                    COUNT(*) FILTER (
                        WHERE order_status IN ('Unshipped', 'PartiallyShipped')
                          AND notified_at IS NULL
                    ) AS unnotified_count,
                    COUNT(*) FILTER (
                        WHERE latest_ship_date IS NOT NULL
                          AND latest_ship_date < NOW()
                          AND order_status IN ('Unshipped', 'PartiallyShipped')
                    ) AS overdue_count
                FROM amazon_orders
                WHERE last_seen_at >= NOW() - make_interval(hours => :hours)
            """),
            {"hours": hours},
        ).fetchone()
        return dict(row._mapping) if row else {
            "open_count": 0,
            "unnotified_count": 0,
            "overdue_count": 0,
        }
