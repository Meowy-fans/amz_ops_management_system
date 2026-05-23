"""Amazon Reports API client."""
import gzip
import io
import time
from typing import Any, Dict, Optional

import requests

from infrastructure.amazon.api_client import AmazonAPIClient
from infrastructure.amazon.config import AmazonConfig


class AmazonReportsClient:
    """Retrieves Amazon listing reports through SP-API."""

    MERCHANT_LISTINGS_ALL_DATA = "GET_MERCHANT_LISTINGS_ALL_DATA"
    MERCHANT_LISTINGS_FYP = "GET_MERCHANTS_LISTINGS_FYP_REPORT"
    DONE = "DONE"
    TERMINAL_FAILURES = {"CANCELLED", "FATAL"}

    def __init__(
        self,
        api_client: Optional[AmazonAPIClient] = None,
        marketplace_id: Optional[str] = None,
        proxy_url: Optional[str] = None,
    ):
        self.api_client = api_client or AmazonAPIClient()
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID
        self.proxy_url = proxy_url if proxy_url is not None else AmazonConfig.HTTPS_PROXY

    def create_merchant_listings_report(self) -> str:
        """Request the all-listings report and return its report id."""
        response = self.api_client.request(
            "POST",
            "/reports/2021-06-30/reports",
            json={
                "reportType": self.MERCHANT_LISTINGS_ALL_DATA,
                "marketplaceIds": [self.marketplace_id],
            },
        )
        return response["body"]["reportId"]

    def create_suppressed_listings_report(
        self,
        locale: str = "en_US",
    ) -> str:
        """Request the Search Suppressed Listings report and return its id."""
        response = self.api_client.request(
            "POST",
            "/reports/2021-06-30/reports",
            json={
                "reportType": self.MERCHANT_LISTINGS_FYP,
                "marketplaceIds": [self.marketplace_id],
                "reportOptions": {"preferredReportDocumentLocale": locale},
            },
        )
        return response["body"]["reportId"]

    def get_report(self, report_id: str) -> Dict[str, Any]:
        """Get report processing status."""
        return self.api_client.request(
            "GET",
            f"/reports/2021-06-30/reports/{report_id}",
        )["body"]

    def wait_for_report(
        self,
        report_id: str,
        poll_interval_seconds: int = 30,
        timeout_seconds: int = 900,
    ) -> str:
        """Wait until a report is done and return the report document id."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            report = self.get_report(report_id)
            status = report.get("processingStatus")
            if status == self.DONE:
                document_id = report.get("reportDocumentId")
                if not document_id:
                    raise RuntimeError(f"Report {report_id} finished without document id")
                return document_id
            if status in self.TERMINAL_FAILURES:
                raise RuntimeError(f"Report {report_id} ended with status {status}")
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Timed out waiting for Amazon report {report_id}")

    def get_report_document(self, report_document_id: str) -> Dict[str, Any]:
        """Get a pre-signed report document download URL."""
        return self.api_client.request(
            "GET",
            f"/reports/2021-06-30/documents/{report_document_id}",
        )["body"]

    def download_report_document(self, document: Dict[str, Any]) -> str:
        """Download a report document through the configured bastion proxy."""
        url = document["url"]
        response = requests.get(
            url,
            timeout=120,
            proxies=self._proxy_dict(),
        )
        response.raise_for_status()
        content = response.content
        if document.get("compressionAlgorithm") == "GZIP":
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
                content = gz.read()
        return content.decode("utf-8-sig")

    def _proxy_dict(self) -> Optional[Dict[str, str]]:
        if not self.proxy_url:
            AmazonConfig.validate_proxy_required()
            return None
        return {
            "http": self.proxy_url,
            "https": self.proxy_url,
        }
