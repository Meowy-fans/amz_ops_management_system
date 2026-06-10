# Amazon Order Sync Module Design

## Status

- Contract status: Frozen (Phase A — read-only orders + human notification)
- Implementation status: Deployed to production (`2026-06-09`)
- Owner modules:
  - `infrastructure/amazon/orders_client.py`
  - `src/services/amazon_order_sync_service.py`
  - `src/services/amazon_order_daily_report_service.py`
  - `src/repositories/amazon_order_repository.py`

## Scope (Phase A)

- Poll Amazon Orders API for recent MFN orders (`Unshipped`, `PartiallyShipped`).
- Persist orders and line items locally; resolve `seller_sku → vendor_sku` via `meow_sku_map`.
- Notify humans via Feishu only when there are **notifyable changes** (new/changed pending orders).
- On sync failure: retry at API layer; alert via Feishu (P1, escalates to P0 after consecutive failures).
- Daily health report at Beijing 09:00 — DB-only summary, no SP-API calls.

Out of scope: Giga auto-ordering, `confirmShipment`, Notifications `ORDER_CHANGE`.

## Services

### `AmazonOrderSyncService`

Responsibility: poll Orders API, upsert local records, send order alerts.

Main method:

- `sync_and_notify(notify: bool | None = None) -> dict`

Behavior:

- `CreatedAfter = now - AMAZON_ORDER_SYNC_LOOKBACK_HOURS` (default 48h).
- Records each run in `amazon_order_sync_runs`.
- Skips Feishu when `count_orders_pending_notification() == 0`.
- Marks `notified_at` only after successful Feishu send (`feishu.is_configured` required).
- Whole-run failure → `_notify_sync_failure`; partial persist errors → `_notify_partial_errors` (P2).

### `AmazonOrderDailyReportService`

Responsibility: compose 24h order + sync health summary from DB.

Main method:

- `run_and_notify(notify: bool | None = None) -> dict`

Behavior:

- Reads `get_order_stats_since`, `get_sync_run_stats_since`, `get_recent_unshipped_summary`.
- Sends Feishu P2 with tags `订单日报`, `健康检查`.
- Window controlled by `AMAZON_ORDER_DAILY_REPORT_HOURS` (default 24).

## CLI Tasks

| Task | Purpose |
|------|---------|
| `sync-amazon-orders` | Manual / scheduled order poll + notify |
| `amazon-order-daily-report` | Manual / scheduled daily health report |
| `test-feishu-alert` | Smoke test for Feishu webhook |

## Production Schedulers

| Container | Script | Default interval |
|-----------|--------|------------------|
| `amz-order-sync-scheduler` | `scripts/sync_amazon_orders_loop.sh` | 1800s (30 min) |
| `amz-order-daily-report-scheduler` | `scripts/amazon_order_daily_report_loop.sh` | Daily 09:00 Asia/Shanghai |

## Database

- Migration: `009_amazon_orders` (`amazon_orders`, `amazon_order_items`, `amazon_order_sync_runs`)
- Alembic version table: service-level (shared Postgres, isolated `amz_listing` database)

## Environment Variables

```env
FEISHU_WEBHOOK_URL=
AMAZON_ORDER_SYNC_NOTIFY=true
AMAZON_ORDER_SYNC_LOOKBACK_HOURS=48
AMAZON_ORDER_SYNC_STATUSES=Unshipped,PartiallyShipped
AMAZON_ORDER_SYNC_INTERVAL_SECONDS=1800
AMAZON_ORDER_SYNC_FAILURE_ALERT_THRESHOLD=3
AMAZON_ORDER_DAILY_REPORT_NOTIFY=true
AMAZON_ORDER_DAILY_REPORT_HOURS=24
AMAZON_ORDER_DAILY_REPORT_HOUR=9
AMAZON_ORDER_DAILY_REPORT_TZ=Asia/Shanghai
```

## Verification Evidence

- Unit tests: `tests/unit/services/test_amazon_order_sync_service.py`, `test_amazon_order_daily_report_service.py`
- Production: Alembic `009_amazon_orders (head)`; 4 containers running; `amazon-order-daily-report` Feishu smoke OK
