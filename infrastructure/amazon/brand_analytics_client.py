"""Amazon Brand Analytics client.

Provides Search Query Performance (SQP) data for keyword share analysis.

Requires: Brand Registry + Brand Analytics role in SP-API.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from infrastructure.amazon.api_client import AmazonAPIClient
from infrastructure.amazon.config import AmazonConfig

logger = logging.getLogger(__name__)


class AmazonBrandAnalyticsClient:
    """Queries Brand Analytics data via SP-API Reports.

    Key endpoint: GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT
    Returns ASIN-level search query metrics:
      - searchQueryVolume, impressions, clicks, cartAdds, purchases
      - query share for each metric
    """

    def __init__(
        self,
        api_client: Optional[AmazonAPIClient] = None,
        marketplace_id: Optional[str] = None,
    ):
        self.api_client = api_client or AmazonAPIClient()
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID

    def request_search_query_performance(
        self,
        asin: str,
        report_period: str = "WEEK",  # DAY, WEEK, MONTH, QUARTER
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """Request an SQP report for a single ASIN.

        Returns a report_id for polling.

        Args:
            asin: Product ASIN.
            report_period: Aggregation period (DAY/WEEK/MONTH/QUARTER).
            start_date: ISO date (defaults to 7 days ago).
            end_date: ISO date (defaults to today).
        """
        if not start_date:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        body = {
            "reportType": "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT",
            "dataStartTime": start_date,
            "dataEndTime": end_date,
            "reportOptions": {
                "reportPeriod": report_period,
                "asin": asin,
            },
            "marketplaceIds": [self.marketplace_id],
        }

        logger.info(
            "Requesting SQP report for ASIN=%s period=%s", asin, report_period
        )
        resp = self.api_client.request(
            "POST",
            "/reporting/reports",
            json=body,
        )
        body_resp = resp.get("body") or resp
        return body_resp.get("reportId", "")

    def get_report_status(self, report_id: str) -> Dict[str, Any]:
        """Check SQP report generation status."""
        resp = self.api_client.request(
            "GET",
            f"/reporting/reports/{report_id}",
        )
        return resp.get("body") or resp

    def download_report(self, report_id: str) -> List[Dict[str, Any]]:
        """Download a completed SQP report."""
        resp = self.api_client.request(
            "GET",
            f"/reporting/reports/{report_id}/document",
        )

        body = resp.get("body") or resp
        document_id = body.get("reportDocumentId", "")
        if not document_id:
            return []

        doc_resp = self.api_client.request(
            "GET",
            f"/reporting/reports/{report_id}/documents/{document_id}",
        )
        doc_body = doc_resp.get("body") or doc_resp
        url = doc_body.get("url", "")
        if not url:
            return []

        import requests

        proxies = AmazonConfig.get_proxy_dict()
        raw = requests.get(url, timeout=30, proxies=proxies).text

        # Parse JSONL format
        rows = []
        for line in raw.strip().split("\n"):
            if line.strip():
                import json
                rows.append(json.loads(line))
        return rows

    def get_sqp_data(
        self,
        asin: str,
        max_wait_seconds: int = 120,
    ) -> List[Dict[str, Any]]:
        """Convenience: request, wait, and download SQP data."""
        import time

        report_id = self.request_search_query_performance(asin)
        if not report_id:
            return []

        for _ in range(max_wait_seconds // 10):
            time.sleep(10)
            status = self.get_report_status(report_id)
            state = status.get("processingStatus", "")
            if state == "DONE":
                return self.download_report(report_id)
            if state in ("FATAL", "CANCELLED"):
                logger.error("SQP report %s failed: %s", report_id, status)
                return []

        logger.warning("SQP report %s timed out", report_id)
        return []

    def extract_share_gaps(
        self,
        sqp_data: List[Dict[str, Any]],
        min_volume: int = 100,
        max_share: float = 0.05,
    ) -> List[Dict[str, Any]]:
        """Identify high-volume queries where our share is low.

        These are keyword opportunities — terms with strong demand
        where we're under-indexing.

        Args:
            sqp_data: Parsed SQP report rows.
            min_volume: Minimum search volume to consider.
            max_share: Maximum click/purchase share to flag as "gap".

        Returns:
            List of gap queries sorted by search volume descending.
        """
        gaps = []
        for row in sqp_data:
            query = row.get("searchQuery", "")
            volume = int(row.get("searchQueryVolume", 0))
            click_share = float(row.get("clickShare", 0))
            purchase_share = float(row.get("purchaseShare", 0))

            if volume >= min_volume and (click_share <= max_share or purchase_share <= max_share):
                gaps.append({
                    "query": query,
                    "volume": volume,
                    "click_share": click_share,
                    "purchase_share": purchase_share,
                    "impressions": int(row.get("impressions", 0)),
                    "clicks": int(row.get("clicks", 0)),
                    "purchases": int(row.get("purchases", 0)),
                })

        gaps.sort(key=lambda x: x["volume"], reverse=True)
        return gaps
