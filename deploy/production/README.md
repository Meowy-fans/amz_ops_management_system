# Production Deployment

This directory is the source-controlled production deployment bundle for `/data/docker-compose/amz-listing-management-system/`.

## Contract

- Runs as a Docker service under `/data/docker-compose/`.
- Uses the shared PostgreSQL container through Docker network DNS: `postgres:5432`.
- Keeps business data under `/data/volumes/amz-listing-management-system/`.
- Does not map host ports. The service joins the external `proxy` network and keeps Traefik disabled by default.
- Stores secrets only in `/data/docker-compose/amz-listing-management-system/.env`.

## Install

```bash
sudo mkdir -p /data/docker-compose/amz-listing-management-system
sudo cp /home/liangqinhao/amz_listing_management_system/deploy/production/docker-compose.yml /data/docker-compose/amz-listing-management-system/docker-compose.yml
sudo cp /home/liangqinhao/amz_listing_management_system/deploy/production/.env.example /data/docker-compose/amz-listing-management-system/.env
```

Edit `.env` with real credentials before starting.

Create a dedicated shared-PostgreSQL database/user before first run:

```bash
docker exec -it postgres psql -U postgres
```

Then create `amz_listing` and `amz_listing` with least required privileges according to `/data/README.md`.

## Deploy

```bash
/home/liangqinhao/amz_listing_management_system/deploy/production/deploy.sh
```

For a one-off CLI task against the production container:

```bash
cd /data/docker-compose/amz-listing-management-system
docker compose run --rm amz-listing-management-system python main.py --task list_categories
```

## Scheduled Sidecars

Production runs three scheduler containers alongside the main service.

### Price/Inventory (hourly)

```bash
python main.py --task update-price-inventory-api --no-dry-run
```

- Container: `amz-price-inventory-scheduler`
- Interval: `PRICE_INVENTORY_UPDATE_INTERVAL_SECONDS` (default `3600`)
- Uses PostgreSQL advisory lock to avoid overlap with manual runs

### Amazon Order Sync (every 30 minutes)

```bash
python main.py --task sync-amazon-orders
```

- Container: `amz-order-sync-scheduler`
- Interval: `AMAZON_ORDER_SYNC_INTERVAL_SECONDS` (default `1800`)
- Notifies Feishu only when pending unnotified orders exist
- Sync failures alert via Feishu (P1; P0 after `AMAZON_ORDER_SYNC_FAILURE_ALERT_THRESHOLD` consecutive failures, default 3)

### Amazon Order Daily Report (Beijing 09:00)

```bash
python main.py --task amazon-order-daily-report
```

- Container: `amz-order-daily-report-scheduler`
- Schedule: `AMAZON_ORDER_DAILY_REPORT_HOUR` / `MINUTE` / `TZ` (default `9:00 Asia/Shanghai`)
- DB-only 24h summary; does not call Orders API

Useful commands:

```bash
cd /data/docker-compose/amz-listing-management-system
docker compose logs -f amz-price-inventory-scheduler
docker compose logs -f amz-order-sync-scheduler
docker compose logs -f amz-order-daily-report-scheduler
docker compose run --rm amz-listing-management-system python main.py --task sync-amazon-orders
docker compose run --rm amz-listing-management-system python main.py --task amazon-order-daily-report
docker compose run --rm amz-listing-management-system python main.py --task test-feishu-alert
```
