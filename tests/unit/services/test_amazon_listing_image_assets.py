"""Unit tests for Amazon listing image asset framework."""

from src.services.amazon_listing_image_inspection_service import (
    AmazonListingImageInspectionService,
)
from src.services.amazon_listing_image_selector import AmazonListingImageSelector


class FakeHttpClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def head(self, url, allow_redirects=True, timeout=10):
        if self.error:
            raise self.error
        return self.response


class FakeResponse:
    def __init__(self, status_code=200, headers=None, url="https://cdn.example/a.jpg"):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url


class FakeRepo:
    def __init__(self, assets):
        self.assets = assets

    def get_assets_for_sku(self, sku):
        return self.assets


def test_inspector_auto_approves_non_supplier_https_image_with_valid_head():
    response = FakeResponse(
        headers={"Content-Type": "image/jpeg", "Content-Length": "120000"}
    )
    service = AmazonListingImageInspectionService(http_client=FakeHttpClient(response))

    result = service.inspect_url("https://cdn.example/a.jpg")

    assert result["review_status"] == "auto_approved"
    assert result["asset_type"] == "raw"
    assert result["content_type"] == "image/jpeg"
    assert result["file_size_bytes"] == 120000
    assert result["rejection_reason"] is None


def test_inspector_marks_supplier_hosted_image_needs_review():
    response = FakeResponse(
        headers={"Content-Type": "image/jpeg", "Content-Length": "120000"}
    )
    service = AmazonListingImageInspectionService(http_client=FakeHttpClient(response))

    result = service.inspect_url("https://b2bfiles1.gigab2b.cn/image/a.jpg")

    assert result["review_status"] == "needs_review"
    assert result["rejection_reason"] == "supplier_hosted_image_requires_review"


def test_inspector_rejects_non_https_or_non_image():
    service = AmazonListingImageInspectionService()

    assert service.inspect_url("http://cdn.example/a.jpg")["review_status"] == "rejected"

    response = FakeResponse(headers={"Content-Type": "text/html"})
    result = AmazonListingImageInspectionService(
        http_client=FakeHttpClient(response)
    ).inspect_url("https://cdn.example/a")

    assert result["review_status"] == "rejected"
    assert result["rejection_reason"] == "unsupported_content_type"


def test_selector_prefers_approved_main_image_then_auto_approved():
    assets = [
        {
            "slot": "main",
            "review_status": "needs_review",
            "storage_url": "https://cdn.example/review.jpg",
            "source_url": "https://cdn.example/review.jpg",
        },
        {
            "slot": "other_1",
            "review_status": "auto_approved",
            "storage_url": "https://cdn.example/auto.jpg",
            "source_url": "https://cdn.example/auto.jpg",
        },
        {
            "slot": "main",
            "review_status": "approved",
            "storage_url": "https://cdn.example/approved.jpg",
            "source_url": "https://cdn.example/approved.jpg",
        },
    ]
    selector = AmazonListingImageSelector(FakeRepo(assets))

    selected = selector.get_approved_images("SKU1")

    assert selected.main_image_url == "https://cdn.example/approved.jpg"
    assert selected.other_image_urls == ["https://cdn.example/auto.jpg"]
