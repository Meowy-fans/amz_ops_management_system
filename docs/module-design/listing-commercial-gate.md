# Listing Commercial Gate Module Design

## Purpose

API listing creation must not submit unsafe price or inventory data. The
commercial gate evaluates each SKU before payload submission and records an
audit trail for every decision.

The goal is not only to block bad data. The goal is to answer:

- What data did we use?
- Which rule version was active?
- Which thresholds applied?
- Why was the SKU allowed or blocked?

## Position In Flow

```text
ProductDataRepository
  -> AmazonListingDraftBuilder
  -> AmazonListingCommercialGate
  -> AmazonListingPayloadBuilder
  -> AmazonListingQualityGate
  -> getListingsItem existing-SKU check
  -> VALIDATION_PREVIEW / putListingsItem
```

`CommercialGate` runs before SP-API attributes are built so it can use source
fields that may not be present in the final payload, such as cost, rule version,
price timestamp, and raw inventory quantities.

## Rule Configuration

Rules live in `config/listing_gates/commercial_gate.yaml`.

Structure:

```yaml
version: commercial_gate_v1
defaults:
  allowed_currency: USD
  price_max_age_hours: 24
  inventory_max_age_hours: 6
  min_margin_rate: 0.25
  max_publish_quantity: 20
  allow_zero_inventory_listing: true
  quantity_source: inventory_quantity
categories:
  CABINET:
    min_margin_rate: 0.30
    max_publish_quantity: 10
```

Category rules override defaults. The merged rule is stored in the audit row as
`rule_snapshot`.

## Inventory Policy

Amazon publish quantity uses `giga_inventory.quantity` only.

`buyer_qty` and `seller_qty` are preserved in `input_snapshot` for audit, but
they are not added to Amazon publish quantity. This avoids accidentally
publishing reserved, buyer-side, or non-sellable stock.

## Audit Table

`amazon_listing_commercial_gate_runs` stores every decision:

- `sku`, `vendor_sku`, `product_type`
- `gate_version`
- `decision`: `passed` or `blocked`
- `blocking_codes`
- `warning_codes`
- `input_snapshot`
- `rule_snapshot`
- `finding_snapshot`
- `created_at`

Both passed and blocked SKUs are persisted.

## Current Blocking Rules

Price:

- missing price
- price <= 0
- unsupported currency
- price older than configured maximum age
- price below category min/max boundaries
- price below cost plus minimum margin
- disallowed pricing formula version when configured

Inventory:

- missing inventory source
- negative inventory
- zero inventory when disabled by config
- publish quantity exceeds category maximum
- inventory older than configured maximum age

## Submission Result

When a SKU is blocked, `generate-listing-api` returns a result item:

```json
{
  "sku": "MEOW1",
  "status": "blocked_commercial_gate",
  "blocking_codes": ["PRICE_STALE"],
  "audit_run_id": 123
}
```

Blocked SKUs do not enter payload generation or the submitter.

## Future Work

1. Add CLI/reporting queries for recent blocked gate runs.
2. Add category-specific formula-version allowlists.
3. Add price-change delta checks against the last Amazon accepted price.
4. Add separate warnings for zero-inventory listing when allowed.
5. Add operator override workflow with reason and expiry.
