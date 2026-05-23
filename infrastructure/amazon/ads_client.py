"""Amazon Ads API client.

Manages Sponsored Products campaigns, keywords, and reports.
Uses Amazon Advertising API (distinct auth from SP-API).

API docs: https://advertising.amazon.com/API/docs/
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from infrastructure.amazon.config import AmazonConfig

logger = logging.getLogger(__name__)


class AdsAPIException(Exception):
    """Amazon Ads API request failure."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AmazonAdsClient:
    """Manages Amazon Sponsored Products via the Advertising API.

    Authentication uses the same SP-API LWA token (requires
    Advertising role in Developer Profile).
    """

    ADS_API_BASE = "https://advertising-api.amazon.com"
    ADS_API_SANDBOX = "https://advertising-api-test.amazon.com"

    RETRY_STATUS_CODES = {429, 500, 503}

    def __init__(
        self,
        api_client: Any = None,
        profile_id: Optional[str] = None,
        sandbox: bool = False,
    ):
        self._sp_api = api_client
        self._profile_id = profile_id or self._default_profile_id()
        self._base_url = self.ADS_API_SANDBOX if sandbox else self.ADS_API_BASE
        self._token: Optional[str] = None
        self._token_expires: float = 0

    # ── Campaign Management ─────────────────────────────────────────

    def create_campaign(
        self,
        name: str,
        budget: float,
        targeting_type: str = "auto",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        bidding_strategy: str = "auto",
    ) -> Dict[str, Any]:
        """Create a new Sponsored Products campaign.

        Args:
            name: Campaign name.
            budget: Daily budget in USD.
            targeting_type: "auto" or "manual".
            start_date: ISO date string (defaults to today).
            bidding_strategy: "auto", "fixed", or "dynamic".
        """
        payload = {
            "name": name,
            "campaignType": "sponsoredProducts",
            "targetingType": "AUTO" if targeting_type == "auto" else "MANUAL",
            "state": "ENABLED",
            "dynamicBidding": {"strategy": "LEGACY_FOR_SALES"},
            "budget": {
                "budgetType": "DAILY",
                "budget": budget,
            },
            "startDate": start_date or datetime.now().strftime("%Y-%m-%d"),
        }
        if end_date:
            payload["endDate"] = end_date

        return self._request("POST", "/v2/sp/campaigns", json=[payload])

    def get_campaigns(self, state_filter: str = "ENABLED") -> List[Dict[str, Any]]:
        """List Sponsored Products campaigns."""
        resp = self._request(
            "GET",
            "/v2/sp/campaigns",
            params={"stateFilter": state_filter},
        )
        return resp if isinstance(resp, list) else resp.get("campaigns", [])

    def update_campaign_budget(self, campaign_id: str, new_budget: float) -> Dict:
        """Update a campaign's daily budget."""
        return self._request(
            "PUT",
            f"/v2/sp/campaigns/{campaign_id}",
            json={"budget": {"budgetType": "DAILY", "budget": new_budget}},
        )

    def pause_campaign(self, campaign_id: str) -> Dict:
        """Pause a campaign."""
        return self._request("PUT", f"/v2/sp/campaigns/{campaign_id}", json={"state": "PAUSED"})

    # ── Ad Group Management ─────────────────────────────────────────

    def create_ad_group(
        self,
        campaign_id: str,
        name: str,
        default_bid: float = 0.50,
    ) -> Dict[str, Any]:
        """Create an ad group within a campaign."""
        payload = {
            "name": name,
            "campaignId": campaign_id,
            "defaultBid": default_bid,
            "state": "ENABLED",
        }
        return self._request("POST", "/v2/sp/adGroups", json=[payload])

    # ── Keyword Management ──────────────────────────────────────────

    def create_keywords(
        self,
        ad_group_id: str,
        campaign_id: str,
        keywords: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Create keywords in an ad group.

        Args:
            ad_group_id: Ad group ID.
            campaign_id: Campaign ID.
            keywords: List of dicts with keys:
                - keywordText (required)
                - matchType: "EXACT", "PHRASE", "BROAD"
                - bid (optional, float)
        """
        payload = []
        for kw in keywords:
            entry = {
                "campaignId": campaign_id,
                "adGroupId": ad_group_id,
                "keywordText": kw["keywordText"],
                "matchType": kw.get("matchType", "BROAD"),
                "state": "ENABLED",
            }
            if "bid" in kw:
                entry["bid"] = kw["bid"]
            payload.append(entry)

        return self._request("POST", "/v2/sp/keywords", json=payload)

    def create_negative_keywords(
        self,
        campaign_id: str,
        keywords: List[str],
        match_type: str = "NEGATIVE_EXACT",
    ) -> Dict[str, Any]:
        """Add negative keywords to a campaign."""
        payload = [
            {
                "campaignId": campaign_id,
                "keywordText": kw,
                "matchType": match_type,
                "state": "ENABLED",
            }
            for kw in keywords
        ]
        return self._request("POST", "/v2/sp/negativeKeywords", json=payload)

    def update_keyword_bid(self, keyword_id: str, new_bid: float) -> Dict:
        """Update a keyword bid."""
        return self._request(
            "PUT",
            f"/v2/sp/keywords/{keyword_id}",
            json={"bid": new_bid},
        )

    def pause_keyword(self, keyword_id: str) -> Dict:
        """Pause a keyword."""
        return self._request(
            "PUT",
            f"/v2/sp/keywords/{keyword_id}",
            json={"state": "PAUSED"},
        )

    # ── Product Targeting (ASIN targeting) ──────────────────────────

    def create_product_targets(
        self,
        ad_group_id: str,
        campaign_id: str,
        asins: List[str],
        bid: float = 0.50,
    ) -> Dict[str, Any]:
        """Target specific ASINs for Sponsored Products."""
        payload = [
            {
                "campaignId": campaign_id,
                "adGroupId": ad_group_id,
                "state": "ENABLED",
                "expression": [{"type": "asin", "value": asin} for asin in asins],
                "bid": bid,
            }
        ]
        return self._request("POST", "/v2/sp/productAds", json=payload)

    # ── Reports ─────────────────────────────────────────────────────

    def request_search_term_report(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """Request a Sponsored Products Search Term Report.

        Returns a report_id that can be polled for completion.
        """
        if not start_date:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        payload = {
            "reportDate": end_date,
            "metrics": "campaignName,campaignId,adGroupName,adGroupId,keywordId,keywordText,matchType,impressions,clicks,cost,attributedSales7d,attributedUnitsOrdered7d,attributedConversions7d",
            "segment": "query",
            "reportFormat": "JSON",
        }

        resp = self._request("POST", "/v2/sp/campaigns/reports", json=payload)
        return resp.get("reportId", "")

    def get_report_status(self, report_id: str) -> Dict[str, Any]:
        """Check the status of a requested report."""
        return self._request("GET", f"/v2/reports/{report_id}")

    def download_report(self, report_id: str) -> List[Dict[str, Any]]:
        """Download a completed report and parse as JSON."""
        resp = self._request("GET", f"/v2/reports/{report_id}/download", raw=True)
        if isinstance(resp, str):
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                # TSV/CSV format — parse line by line
                lines = resp.strip().split("\n")
                if len(lines) < 2:
                    return []
                headers = lines[0].split("\t")
                rows = []
                for line in lines[1:]:
                    values = line.split("\t")
                    rows.append(dict(zip(headers, values)))
                return rows
        return resp if isinstance(resp, list) else []

    def request_and_download_report(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_wait_seconds: int = 120,
    ) -> List[Dict[str, Any]]:
        """Request, wait for, and download a search term report.

        Returns parsed report rows.
        """
        report_id = self.request_search_term_report(start_date, end_date)
        if not report_id:
            logger.error("Failed to request search term report")
            return []

        logger.info("Requested search term report: %s", report_id)

        # Poll for completion
        for _ in range(max_wait_seconds // 10):
            time.sleep(10)
            status = self.get_report_status(report_id)
            state = status.get("status", "")
            if state == "COMPLETED":
                logger.info("Report %s completed", report_id)
                return self.download_report(report_id)
            if state == "FAILED":
                logger.error("Report %s failed: %s", report_id, status)
                return []

        logger.warning("Report %s timed out after %ds", report_id, max_wait_seconds)
        return []

    # ── HTTP ────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Get Ads API access token via LWA."""
        if self._token and time.time() < self._token_expires - 300:
            return self._token

        AmazonConfig.validate_credentials()
        proxies = AmazonConfig.get_proxy_dict()

        resp = requests.post(
            "https://api.amazon.com/auth/o2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": AmazonConfig.REFRESH_TOKEN,
                "client_id": AmazonConfig.LWA_CLIENT_ID,
                "client_secret": AmazonConfig.LWA_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
            proxies=proxies,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json: Optional[Any] = None,
        raw: bool = False,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Amazon-Advertising-API-ClientId": AmazonConfig.LWA_CLIENT_ID or "",
        }
        if self._profile_id:
            headers["Amazon-Advertising-API-Scope"] = self._profile_id
        if json is not None:
            headers["Content-Type"] = "application/json"

        proxies = AmazonConfig.get_proxy_dict()

        for attempt in range(4):
            resp = requests.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=30,
                proxies=proxies,
            )
            if resp.status_code in self.RETRY_STATUS_CODES and attempt < 3:
                time.sleep(2 ** attempt)
                continue

            if resp.status_code >= 400:
                logger.error(
                    "Ads API error %d: %s",
                    resp.status_code,
                    resp.text[:300],
                )
                raise AdsAPIException(
                    f"Ads API request failed: {resp.status_code}",
                    status_code=resp.status_code,
                )

            if raw:
                return resp.text

            if not resp.text:
                return {}
            return resp.json()

        raise AdsAPIException("Ads API retry loop exhausted")

    @staticmethod
    def _default_profile_id() -> Optional[str]:
        import os
        return os.getenv("AMAZON_ADS_PROFILE_ID")
