"""Deterministic image inspection for Amazon listing assets."""

from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests


class AmazonListingImageInspectionService:
    """Runs safe, deterministic checks for image URLs.

    This service intentionally does not decide visual compliance such as white
    background, watermark, OCR, or product fill ratio yet. Those checks should
    plug into the same result contract later and move uncertain assets to
    needs_review instead of auto_approved.
    """

    SUPPLIER_HOST_PATTERNS = ("gigab2b", "b2bfiles")
    SUPPORTED_CONTENT_TYPES = {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
    }

    def __init__(
        self,
        http_client: Any = None,
        timeout: int = 10,
        min_file_size_bytes: int = 1024,
    ):
        self.http_client = http_client or requests
        self.timeout = timeout
        self.min_file_size_bytes = min_file_size_bytes

    def inspect_url(self, url: str) -> Dict[str, Any]:
        parsed = urlparse(str(url or ""))
        base = {
            "asset_type": "raw",
            "source_url": url,
            "storage_url": None,
            "content_type": None,
            "file_size_bytes": None,
            "width": None,
            "height": None,
            "checksum": None,
            "review_status": "rejected",
            "rejection_reason": None,
            "inspection_result": {},
        }

        if parsed.scheme != "https" or not parsed.netloc:
            return self._reject(base, "invalid_https_url")

        try:
            response = self.http_client.head(
                url,
                allow_redirects=True,
                timeout=self.timeout,
            )
        except Exception as exc:
            return self._reject(base, "head_request_failed", {"error": str(exc)})

        base["inspection_result"] = {"http_status": response.status_code}
        if response.status_code >= 400:
            return self._reject(base, "http_status_not_ok")

        content_type = self._clean_content_type(response.headers.get("Content-Type"))
        base["content_type"] = content_type
        if content_type not in self.SUPPORTED_CONTENT_TYPES:
            return self._reject(base, "unsupported_content_type")

        size = self._to_int(response.headers.get("Content-Length"))
        base["file_size_bytes"] = size
        if size is not None and size < self.min_file_size_bytes:
            return self._reject(base, "image_file_too_small")

        final_host = urlparse(getattr(response, "url", url)).netloc
        host_for_policy = final_host or parsed.netloc
        if self._is_supplier_hosted(parsed.netloc) or self._is_supplier_hosted(
            host_for_policy
        ):
            base["review_status"] = "needs_review"
            base["rejection_reason"] = "supplier_hosted_image_requires_review"
            return base

        base["review_status"] = "auto_approved"
        return base

    @classmethod
    def _is_supplier_hosted(cls, host: str) -> bool:
        host_l = str(host or "").lower()
        return any(pattern in host_l for pattern in cls.SUPPLIER_HOST_PATTERNS)

    @staticmethod
    def _clean_content_type(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return value.split(";")[0].strip().lower()

    @staticmethod
    def _to_int(value: Optional[str]) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _reject(
        result: Dict[str, Any],
        reason: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result["review_status"] = "rejected"
        result["rejection_reason"] = reason
        if extra:
            result["inspection_result"].update(extra)
        return result
