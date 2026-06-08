"""Repository for product image assets used by Amazon listing creation."""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class AmazonListingImageAssetRepository:
    """Persists image asset inspection and review state.

    State model:
    - raw: URL was discovered but not inspected.
    - auto_approved: deterministic checks passed and policy allows automatic use.
    - needs_review: technically usable, but requires human review before live submit.
    - approved: human-approved image.
    - rejected: cannot be used.
    - processing_failed: inspection/download/processing failed.

    Later image editing, object storage upload, OCR, white-background checks, and
    review UI should update this same table instead of bypassing the asset layer.
    """

    def __init__(self, db: Session):
        self.db = db

    def upsert_asset(
        self,
        sku: str,
        source_url: str,
        vendor_sku: Optional[str] = None,
        storage_url: Optional[str] = None,
        asset_type: str = "raw",
        slot: str = "other",
        review_status: str = "raw",
        rejection_reason: Optional[str] = None,
        checksum: Optional[str] = None,
        content_type: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        inspection_result: Optional[Dict[str, Any]] = None,
    ) -> int:
        query = text("""
            INSERT INTO product_image_assets (
                sku, vendor_sku, source_url, storage_url, asset_type, slot,
                review_status, rejection_reason, checksum, content_type,
                file_size_bytes, width, height, inspection_result, updated_at
            ) VALUES (
                :sku, :vendor_sku, :source_url, :storage_url, :asset_type, :slot,
                :review_status, :rejection_reason, :checksum, :content_type,
                :file_size_bytes, :width, :height, :inspection_result, NOW()
            )
            ON CONFLICT (sku, source_url) DO UPDATE SET
                vendor_sku = EXCLUDED.vendor_sku,
                storage_url = EXCLUDED.storage_url,
                asset_type = EXCLUDED.asset_type,
                slot = EXCLUDED.slot,
                review_status = EXCLUDED.review_status,
                rejection_reason = EXCLUDED.rejection_reason,
                checksum = EXCLUDED.checksum,
                content_type = EXCLUDED.content_type,
                file_size_bytes = EXCLUDED.file_size_bytes,
                width = EXCLUDED.width,
                height = EXCLUDED.height,
                inspection_result = EXCLUDED.inspection_result,
                updated_at = NOW()
            RETURNING id
        """)
        result = self.db.execute(
            query,
            {
                "sku": sku,
                "vendor_sku": vendor_sku,
                "source_url": source_url,
                "storage_url": storage_url,
                "asset_type": asset_type,
                "slot": slot,
                "review_status": review_status,
                "rejection_reason": rejection_reason,
                "checksum": checksum,
                "content_type": content_type,
                "file_size_bytes": file_size_bytes,
                "width": width,
                "height": height,
                "inspection_result": (
                    json.dumps(inspection_result) if inspection_result else None
                ),
            },
        )
        self.db.commit()
        return result.scalar_one()

    def get_assets_for_sku(self, sku: str) -> List[Dict[str, Any]]:
        query = text("""
            SELECT
                id, sku, vendor_sku, source_url, storage_url, asset_type, slot,
                review_status, rejection_reason, checksum, content_type,
                file_size_bytes, width, height, inspection_result,
                reviewed_by, reviewed_at, created_at, updated_at
            FROM product_image_assets
            WHERE sku = :sku
            ORDER BY
                CASE review_status
                    WHEN 'approved' THEN 1
                    WHEN 'auto_approved' THEN 2
                    WHEN 'needs_review' THEN 3
                    ELSE 4
                END,
                CASE slot WHEN 'main' THEN 1 ELSE 2 END,
                id
        """)
        rows = self.db.execute(query, {"sku": sku}).mappings().all()
        return [dict(row) for row in rows]

    def mark_review_status(
        self,
        asset_id: int,
        review_status: str,
        reviewed_by: str,
        rejection_reason: Optional[str] = None,
    ) -> None:
        query = text("""
            UPDATE product_image_assets
            SET review_status = :review_status,
                rejection_reason = :rejection_reason,
                reviewed_by = :reviewed_by,
                reviewed_at = NOW(),
                updated_at = NOW()
            WHERE id = :asset_id
        """)
        self.db.execute(
            query,
            {
                "asset_id": asset_id,
                "review_status": review_status,
                "rejection_reason": rejection_reason,
                "reviewed_by": reviewed_by,
            },
        )
        self.db.commit()
