# Schema-driven Attribute Resolution Production Deploy Report

> Date: 2026-06-15  
> Agent: Cursor  
> Epic: `EPIC-AMZ-SCHEMA-DRIVEN-ATTRIBUTES`  
> Task: TASK-142  
> Image: `amz-listing-management-system:2026-06-15-schema-driven-attributes`

## 1. Scope

This deployment ships the schema-driven attribute resolution Epic:

- TASK-138: coverage required = top-level/direct schema required + Amazon
  preview-learned `90220` required feedback.
- TASK-139: schema property allowlist and generic renderer shape support.
- TASK-140: constrained LLM attribute extraction interface.
- TASK-141: config-driven PayloadBuilder slimming.
- HOME_MIRROR required rule completion for the previously failing 10 required
  attributes.

## 2. Production Deployment

Production compose image tag:

```text
amz-listing-management-system:2026-06-15-schema-driven-attributes
```

Deployment command used a clean compose environment to avoid shell env leaking
into production containers:

```bash
env -u DATABASE_HOST -u DATABASE_PORT -u DATABASE_NAME -u DATABASE_USER \
  -u DATABASE_PASSWORD -u POSTGRES_USER -u POSTGRES_PASSWORD \
  -u AMAZON_REFRESH_TOKEN -u AMAZON_LWA_CLIENT_ID -u AMAZON_LWA_CLIENT_SECRET \
  docker compose -f /data/docker-compose/amz-listing-management-system/docker-compose.yml \
  --env-file /data/docker-compose/amz-listing-management-system/.env build

env -u DATABASE_HOST -u DATABASE_PORT -u DATABASE_NAME -u DATABASE_USER \
  -u DATABASE_PASSWORD -u POSTGRES_USER -u POSTGRES_PASSWORD \
  -u AMAZON_REFRESH_TOKEN -u AMAZON_LWA_CLIENT_ID -u AMAZON_LWA_CLIENT_SECRET \
  docker compose -f /data/docker-compose/amz-listing-management-system/docker-compose.yml \
  --env-file /data/docker-compose/amz-listing-management-system/.env up -d --force-recreate
```

## 3. Validation

Local full regression:

```bash
./.venv/bin/pytest -q
git diff --check
```

Result: all tests passed; whitespace check passed.

Production smoke:

```bash
docker compose -f /data/docker-compose/amz-listing-management-system/docker-compose.yml \
  --env-file /data/docker-compose/amz-listing-management-system/.env ps
docker exec amz-listing-management-system python main.py --task list-categories
curl -I https://amz-listing.meowy.fans
```

Result:

- Main container healthy.
- `amz-price-inventory-scheduler`, `amz-order-sync-scheduler`, and
  `amz-order-daily-report-scheduler` running.
- `list-categories` returns `CABINET` and `HOME_MIRROR`.
- Public route returns SSO redirect (`302`).

HOME_MIRROR strict dry-run:

```bash
docker exec amz-listing-management-system python main.py \
  --task generate-listing-api \
  --category HOME_MIRROR \
  --strict-validation \
  --only-not-on-amazon
```

Result:

- 6 generated plans.
- 6 `validation_preview_passed`.
- 0 issues.
- 0 PUT calls.
- 12 `skipped_existing_scope`.
- 7 `blocked_variation_resolution`.

Validated SKUs:

- `meow251108CqW5i`
- `meow251108lbxoE`
- `meow251108GRUGR`
- `meow251108oXHVM`
- `meow251108wFRxA`
- `meow251108RA1v0`

OTTOMAN strict smoke:

- Parent `PARENT-50DEF22E2FE3`: `validation_preview_passed`, issues=0.
- Children `meow2511088jSUW` and `meow260518LZZCw`: `skipped_existing`.

CABINET 18-SKU regression:

- No `blocked_attribute_coverage` remains after config-driven parent ignore and
  additional `item_width` measure.
- 1 existing `blocked_variation_resolution` remains.
- 14 `skipped_existing_scope`.
- 4 `validation_preview_issues`, each the known TASK-134 width >42in Amazon
  warning / business live blocker.
- 0 PUT calls.

## 4. Operational Notes

- `/data/README.md` and `/data/TODO.md` were updated with the new image tag and
  deployment summary.
- The production deployment reused the existing shared PostgreSQL database and
  did not introduce a migration.
- CABINET width >42in remains governed by
  `docs/decisions/ADR-2026-06-15-cabinet-48in-live-policy.md`.

## 5. Residual Risk

- HOME_MIRROR now passes validation preview for the currently unblocked plans,
  but 7 variation-family SKUs still fail earlier variation resolution and need a
  separate variation data cleanup/decision task.
- LLM extraction is available as an injectable constrained layer; no production
  prompt/client is enabled for automatic attribute extraction in this deployment.
