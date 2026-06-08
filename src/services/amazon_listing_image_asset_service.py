"""Image asset orchestration for API-native Amazon listing creation."""

from typing import Any, Dict, List

from src.repositories.amazon_listing_image_asset_repository import (
    AmazonListingImageAssetRepository,
)
from src.services.amazon_listing_image_inspection_service import (
    AmazonListingImageInspectionService,
)


class AmazonListingImageAssetService:
    """Registers and inspects supplier images for later listing selection.

    First implementation scope:
    - discover image URLs from product raw_data
    - run deterministic URL/content checks
    - persist raw/auto_approved/needs_review/rejected status

    Reserved extension points:
    - download and checksum file contents
    - image dimension extraction
    - white-background / OCR / watermark checks
    - background removal and processed image generation
    - object storage upload and human review UI
    """

    def __init__(
        self,
        db,
        image_asset_repo: AmazonListingImageAssetRepository | None = None,
        inspector: AmazonListingImageInspectionService | None = None,
    ):
        self.db = db
        self.image_asset_repo = image_asset_repo or AmazonListingImageAssetRepository(db)
        self.inspector = inspector or AmazonListingImageInspectionService()

    def register_product_images(self, product_data: Dict[str, Any]) -> List[int]:
        sku = str(product_data.get("meow_sku") or "").strip()
        vendor_sku = str(product_data.get("vendor_sku") or "").strip()
        raw_data = product_data.get("raw_data") or {}
        if not sku or not raw_data:
            return []

        urls = self._image_urls(raw_data)
        asset_ids = []
        for idx, url in enumerate(urls):
            inspection = self.inspector.inspect_url(url)
            slot = "main" if idx == 0 else f"other_{idx}"
            asset_ids.append(
                self.image_asset_repo.upsert_asset(
                    sku=sku,
                    vendor_sku=vendor_sku,
                    source_url=url,
                    storage_url=inspection.get("storage_url"),
                    asset_type=inspection.get("asset_type", "raw"),
                    slot=slot,
                    review_status=inspection["review_status"],
                    rejection_reason=inspection.get("rejection_reason"),
                    checksum=inspection.get("checksum"),
                    content_type=inspection.get("content_type"),
                    file_size_bytes=inspection.get("file_size_bytes"),
                    width=inspection.get("width"),
                    height=inspection.get("height"),
                    inspection_result=inspection.get("inspection_result"),
                )
            )
        return asset_ids

    @staticmethod
    def _image_urls(raw_data: Dict[str, Any]) -> List[str]:
        urls = []
        main = str(raw_data.get("mainImageUrl") or "").strip()
        if main:
            urls.append(main)
        for url in raw_data.get("imageUrls") or []:
            text = str(url or "").strip()
            if text and text not in urls:
                urls.append(text)
        return urls
