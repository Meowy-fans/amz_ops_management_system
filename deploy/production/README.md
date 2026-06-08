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

## Scheduled Price/Inventory Updates

Production starts `amz-price-inventory-scheduler` alongside the main service. It
runs the API-native price/inventory update every hour:

```bash
python main.py --task update-price-inventory-api --no-dry-run
```

The interval is controlled by `PRICE_INVENTORY_UPDATE_INTERVAL_SECONDS` and
defaults to `3600`. The scheduler uses an application-level PostgreSQL advisory
lock, so a manual run and a scheduled run will not overlap.

Useful commands:

```bash
cd /data/docker-compose/amz-listing-management-system
docker compose logs -f amz-price-inventory-scheduler
docker compose run --rm amz-listing-management-system python main.py --task update-price-inventory-api --no-dry-run
```
