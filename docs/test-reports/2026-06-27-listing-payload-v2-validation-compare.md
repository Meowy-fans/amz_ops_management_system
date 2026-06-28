# Listing Payload Engine V2 Validation Compare - 2026-06-27

## Scope

Close the S14 gate `ValidationPreviewV2.compare()` for representative canary SKUs.
Validation compare now builds plans through the same authoritative path as
`generate-listing-api --engine v2`, then runs Amazon `VALIDATION_PREVIEW` and
checks that Amazon-only issues are either absent or explainable.

## Fixes

1. `ProductListingAPIPlanBuilder.build_v2_payload_plan_for_sku()` — single-SKU
   authoritative plan build (commercial gate, images, variation append, V2 coverage).
2. `evaluate-listing-v2-validation-compare` and `validate-listing-v2` use the
   authoritative builder instead of `build_read_only_plan()`.
3. `ListingPayloadEngineV2` applies YAML `post_processors` (CABINET door shape)
   and V1 parity for universal identifier attributes.
4. `ValidationPreviewV2.unexplained_amazon_only()` honors
   `coverage_ignore_required` from category rules.
5. `PayloadComposerV2` / `RequirementTreeBuilderV2` support `measure_array`
   (e.g. OTTOMAN `seat.height`) to match Amazon array-of-measure schema shape.

## Production Evidence

Command (requires both env files for SP-API credentials):

```bash
docker run --rm --network proxy \
  -v /home/liangqinhao/amz_listing_management_system:/app \
  --env-file /data/docker-compose/amz-listing-management-system/.env \
  --env-file /data/docker-compose/amz-listing-management-system/.env.amazon-sp-api \
  -e DATABASE_HOST=postgres -e APP_MODE=cli -w /app \
  amz-listing-management-system:2026-06-25-confidence-review-pipeline \
  python main.py --task evaluate-listing-v2-validation-compare
```

Result: `status=go total=3 go=3 no_go=0`

| Product type | SKU | Preview | Unexplained Amazon-only |
| --- | --- | --- | --- |
| CABINET | `meow251115FC0ie` | `validation_preview_passed` | 0 |
| HOME_MIRROR | `meow251108CqW5i` | `validation_preview_passed` | 0 |
| OTTOMAN | `meow2511088jSUW` | `validation_preview_passed` | 0 |

## Verification

Targeted unit tests for validation compare, preview, engine, composer, tree
builder, and plan builder: 64 passed.

## Remaining Gate

- `--engine v2 --no-dry-run` remains blocked.
- V2 code is in the production image `2026-06-27-listing-payload-v2`.
- LIVE canary still needs additional non-existing SKU strict-preview evidence
  before unblocking `--engine v2 --no-dry-run`.
