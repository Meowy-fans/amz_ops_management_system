"""Delayed confirmation pass for Amazon price/inventory updates."""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from src.repositories.amazon_api_submission_repository import (
    AmazonAPISubmissionRepository,
)
from src.repositories.amazon_listing_item_cache_repository import (
    AmazonListingItemCacheRepository,
)
from src.services.amazon_price_inventory_update_service import (
    AmazonPriceInventoryUpdateService,
)
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class AmazonPriceInventoryDelayedConfirmationService:
    """Re-checks accepted price/inventory patches after Amazon propagation delay."""

    def __init__(
        self,
        db,
        reporter: Optional[ProgressReporter] = None,
        listings_client: Any = None,
        submission_repo: Any = None,
        cache_repo: Any = None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self.submission_repo = submission_repo or AmazonAPISubmissionRepository(db)
        self.cache_repo = cache_repo or AmazonListingItemCacheRepository(db)

    def confirm_pending(
        self,
        older_than_minutes: int = 30,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        candidates = self.submission_repo.get_delayed_confirmation_candidates(
            older_than_minutes=older_than_minutes,
            limit=limit,
        )
        if not candidates:
            self.reporter.emit("No delayed price/inventory confirmations pending.")
            return []

        client = self._listings_client()
        results = []
        for candidate in candidates:
            result = self._confirm_one(client, candidate, older_than_minutes)
            results.append(result)

        self._emit_summary(results)
        return results

    def _confirm_one(
        self,
        client: Any,
        candidate: Dict[str, Any],
        older_than_minutes: int,
    ) -> Dict[str, Any]:
        source_id = candidate["id"]
        sku = candidate["sku"]
        target_price, target_quantity = self._extract_targets(
            self._as_dict(candidate.get("request_payload"))
        )
        marketplace_id = candidate.get("marketplace_id") or os.environ.get(
            "AMAZON_MARKETPLACE_ID", "ATVPDKIKX0DER"
        )

        try:
            response = client.get_listings_item(
                sku=sku,
                included_data=AmazonPriceInventoryUpdateService.INCLUDED_DATA,
            )
            body = response.get("body", {})
            if body:
                self.cache_repo.upsert_items([body])
            confirmation = self._classify_confirmation(body, target_price, target_quantity)
            status = confirmation["status"]
            response_body = {
                "source_submission_id": source_id,
                "source_status": candidate.get("status"),
                "target_price": target_price,
                "target_quantity": target_quantity,
                "confirmation": confirmation,
            }
            request_id = response.get("headers", {}).get("x-amzn-RequestId", "")
            error_message = None
        except Exception as exc:
            status = "delayed_confirmation_failed"
            request_id = ""
            error_message = str(exc)
            response_body = {
                "source_submission_id": source_id,
                "source_status": candidate.get("status"),
                "target_price": target_price,
                "target_quantity": target_quantity,
            }

        self.submission_repo.insert_submission(
            sku=sku,
            operation="delayed_confirmation",
            status=status,
            amazon_request_id=request_id,
            marketplace_id=marketplace_id,
            product_type=candidate.get("product_type"),
            request_payload={
                "source_submission_id": source_id,
                "source_status": candidate.get("status"),
                "older_than_minutes": older_than_minutes,
            },
            response_body=response_body,
            error_message=error_message,
        )
        return {"sku": sku, "source_id": source_id, "status": status}

    def _classify_confirmation(
        self,
        body: Dict[str, Any],
        target_price: Optional[float],
        target_quantity: Optional[int],
    ) -> Dict[str, Any]:
        issues = body.get("issues") or []
        mismatches = self._target_mismatches(body, target_price, target_quantity)
        if issues and mismatches:
            status = "delayed_confirmed_with_issues_and_mismatch"
        elif issues:
            status = "delayed_confirmed_with_issues"
        elif mismatches:
            status = "delayed_confirmed_with_mismatch"
        else:
            status = "delayed_update_confirmed"
        return {
            "status": status,
            "issues": len(issues),
            "body": body,
            "mismatches": mismatches,
        }

    @staticmethod
    def _target_mismatches(
        body: Dict[str, Any],
        target_price: Optional[float],
        target_quantity: Optional[int],
    ) -> Dict[str, Any]:
        mismatches: Dict[str, Any] = {}
        current_price = AmazonPriceInventoryUpdateService._extract_price(body)
        current_quantity = AmazonPriceInventoryUpdateService._extract_quantity(body)
        if target_price is not None and not AmazonPriceInventoryUpdateService._same_number(
            current_price, target_price
        ):
            mismatches["price"] = {
                "expected": float(target_price),
                "actual": current_price,
            }
        if target_quantity is not None and current_quantity != int(target_quantity):
            mismatches["quantity"] = {
                "expected": int(target_quantity),
                "actual": current_quantity,
            }
        return mismatches

    @staticmethod
    def _extract_targets(payload: Dict[str, Any]) -> Tuple[Optional[float], Optional[int]]:
        price = None
        quantity = None
        for patch in payload.get("patches") or []:
            value = patch.get("value") or []
            if patch.get("path") == "/attributes/purchasable_offer":
                try:
                    price = float(
                        value[0]["our_price"][0]["schedule"][0]["value_with_tax"]
                    )
                except (KeyError, IndexError, TypeError, ValueError):
                    pass
            if patch.get("path") == "/attributes/fulfillment_availability":
                try:
                    quantity = int(value[0]["quantity"])
                except (KeyError, IndexError, TypeError, ValueError):
                    pass
        return price, quantity

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            return json.loads(value)
        return {}

    def _listings_client(self):
        if self._listings_client_instance is not None:
            return self._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self._listings_client_instance = AmazonListingsClient()
        return self._listings_client_instance

    def _emit_summary(self, results: List[Dict[str, Any]]) -> None:
        counts: Dict[str, int] = {}
        for result in results:
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        self.reporter.emit(f"Delayed confirmation complete: {len(results)} records")
        for status, count in sorted(counts.items()):
            self.reporter.emit(f"  {status}: {count}")
