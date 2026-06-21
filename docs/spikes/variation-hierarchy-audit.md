# Variation Hierarchy Audit Spike

## Goal

Before blocking LIVE variation append operations, validate that Amazon read APIs can provide enough online family facts to compare a new child against existing sibling variation attributes.

## Read-Only Probe

Implemented module: `src/services/variation_hierarchy_probe.py`.

Current probe flow:

1. Call `getListingsItem(parent_sku, includedData=["summaries", "attributes", "productTypes"])`.
2. Extract parent ASIN from listing summaries.
3. Call `getCatalogItem(parent_asin, includedData=["relationships"])`.
4. Extract child ASIN candidates from the relationship payload.
5. Return a machine-readable snapshot without mutating Amazon or local state.

## Integration Plan

- Keep the probe separate from `AmazonVariationResolver` until live API payload shapes are confirmed with real parent listings.
- After confirmation, add a `VariationHierarchyAuditGate` before `resolve_append_child` accepts a child.
- Reuse `amazon_variation_resolution_runs` for the first audit snapshot. Add a dedicated conflict table only if querying conflicts becomes painful.

## Open Verification

- Confirm the exact `relationships` response shape for production parent ASINs.
- Confirm whether Catalog relationships include seller SKU, or whether child ASINs must be mapped back through Listings Items / local reports.
- Confirm rate limits for the parent relationship call plus child attribute lookups.
