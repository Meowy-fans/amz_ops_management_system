# Listing Image Assets Module Design

## Purpose

API-native listing creation should not submit supplier image URLs directly.
Supplier images are raw materials.  The listing path should use image assets
that have been inspected, reviewed, or processed by our own pipeline.

This module creates the framework for that pipeline while keeping the first
implementation deliberately small and deterministic.

## Core Flow

```text
Giga raw image URLs
  -> product_image_assets raw rows
  -> deterministic inspection
  -> review_status decision
  -> optional human review / processing
  -> approved image selection
  -> SP-API listing payload
```

The listing submission path only reads approved asset decisions. It does not
download, inspect, or mutate image state while building a payload.

## Data Model

`product_image_assets` stores one row per SKU/source URL:

- `sku`, `vendor_sku`
- `source_url`: original supplier or processed source URL.
- `storage_url`: future self-hosted CDN/object-storage URL.
- `asset_type`: `raw`, `processed`, or future specialized types.
- `slot`: `main`, `other_1`, `other_2`, ...
- `review_status`
- `rejection_reason`
- `checksum`, `content_type`, `file_size_bytes`, `width`, `height`
- `inspection_result`
- `reviewed_by`, `reviewed_at`

The unique key is `(sku, source_url)` so repeated inspection updates the same
asset row.

## Status Model

- `raw`: URL was discovered but not inspected.
- `auto_approved`: deterministic checks passed and policy allows automatic use.
- `needs_review`: technically usable, but not safe for live listing without human review.
- `approved`: human-approved image.
- `rejected`: cannot be used.
- `processing_failed`: future image processing failed.

Only `approved` and `auto_approved` images are selected for API listing payloads.

## Current Implementation

Implemented:

- HTTPS URL validation.
- HEAD request status check.
- `Content-Type` check for image MIME types.
- `Content-Length` minimum-size check.
- Supplier-hosted URL detection for `gigab2b` / `b2bfiles`.
- Asset upsert and SKU lookup.
- Approved image selection.
- API listing payload path prefers approved assets when present.

Not implemented yet:

- Image download and checksum from file bytes.
- Width/height extraction.
- White-background detection.
- OCR / watermark / logo detection.
- Product fill-ratio detection.
- Automatic background removal and processed image creation.
- Object storage / CDN upload.
- Human review UI.

## Module Boundaries

`AmazonListingImageAssetService`

Discovers image URLs from product raw data, runs deterministic inspection, and
persists asset rows. Later image processing and object-storage upload should be
added here or in collaborators called by this service.

`AmazonListingImageInspectionService`

Runs deterministic technical checks. It should return `needs_review` when an
image is technically reachable but visual compliance is uncertain.

`AmazonListingImageSelector`

Reads image asset rows and returns only approved images for listing payloads.
It does not perform inspection or review.

`ProductListingService`

During API-native plan building, it calls the selector and overrides raw
supplier images only when approved images exist. If the image asset table is not
available yet, selection is skipped and the existing quality gate remains the
fallback blocker.

## Future Work

1. Add an explicit CLI task such as `inspect-listing-images`.
2. Download images and compute checksum from bytes.
3. Extract width/height with Pillow.
4. Add object storage upload and write `storage_url`.
5. Add human review workflow for `needs_review`.
6. Add visual checks: white background, text/watermark, product fill ratio.
7. Make live submit require approved or auto-approved main image by default.
