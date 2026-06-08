"""API-native price and inventory update flow for existing Amazon listings."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from infrastructure.amazon.api_client import AmazonAPIException
from src.repositories.amazon_listing_item_cache_repository import (
    AmazonListingItemCacheRepository,
)
from src.repositories.amazon_api_submission_repository import (
    AmazonAPISubmissionRepository,
)
from src.repositories.amz_listing_data_repository import ListingDataRepository
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class AmazonPriceInventoryUpdateService:
    """Updates existing listing price and inventory using Listings Items API."""

    INCLUDED_DATA = [
        "summaries",
        "attributes",
        "issues",
        "offers",
        "fulfillmentAvailability",
        "productTypes",
    ]

    def __init__(
        self,
        db,
        reporter: Optional[ProgressReporter] = None,
        listings_client: Any = None,
        submission_repo: Any = None,
        listing_data_repo: Any = None,
        cache_repo: Any = None,
        sync_latest_data=None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self.submission_repo = submission_repo or AmazonAPISubmissionRepository(db)
        self.listing_data_repo = listing_data_repo or ListingDataRepository(db)
        self.cache_repo = cache_repo or AmazonListingItemCacheRepository(db)
        self.sync_latest_data = sync_latest_data

    def submit_updates_via_api(self, dry_run: bool = True) -> List[Dict[str, Any]]:
        if self.sync_latest_data:
            self.sync_latest_data()
        self._sync_listing_cache()

        sku_map = self.listing_data_repo.get_skus_for_update()
        if not sku_map:
            self.reporter.emit("No SKUs found for update. Exiting.")
            return []

        amazon_skus = list({item["amazon_sku"] for item in sku_map})
        giga_skus = list({item["giga_sku"] for item in sku_map})
        price_map, quantity_map = self.listing_data_repo.get_latest_data(
            amazon_skus, giga_skus
        )
        marketplace_id = os.environ.get("AMAZON_MARKETPLACE_ID", "ATVPDKIKX0DER")

        results: List[Dict[str, Any]] = []
        client = self._listings_client()
        for item in sku_map:
            result = self._process_one(
                item=item,
                price=price_map.get(item["amazon_sku"]),
                quantity=quantity_map.get(item["giga_sku"]),
                marketplace_id=marketplace_id,
                dry_run=dry_run,
                client=client,
            )
            if result is not None:
                results.append(result)

        self._emit_summary(results)
        return results

    def _sync_listing_cache(self) -> int:
        client = self._listings_client()
        page_token = None
        total = 0
        while True:
            response = client.search_listings_items(
                included_data=self.INCLUDED_DATA,
                page_size=20,
                page_token=page_token,
            )
            body = response.get("body", {})
            items = body.get("items") or []
            total += self.cache_repo.upsert_items(items)
            page_token = self._next_page_token(body)
            if not page_token:
                break
        return total

    def _process_one(
        self,
        item: Dict[str, Any],
        price: Optional[float],
        quantity: Optional[int],
        marketplace_id: str,
        dry_run: bool,
        client: Any,
    ) -> Optional[Dict[str, Any]]:
        sku = item["amazon_sku"]
        if price is None and quantity is None:
            self.reporter.emit(f"  SKIP {sku}: no price or quantity data")
            return None

        current = self._get_listing_for_update(client, sku)
        if current["status"] != "found":
            self._record(
                sku=sku,
                operation="both",
                status=current["status"],
                product_type=item.get("product_type") or "PRODUCT",
                marketplace_id=marketplace_id,
                request_payload={},
                response_body=current.get("body"),
                error_message=current.get("error"),
            )
            return {"sku": sku, "status": current["status"], "error": current.get("error")}

        body = current["body"]
        issues = body.get("issues") or []
        product_type = self._product_type(body, item)
        if self._has_blocking_issues(issues):
            self._record(
                sku=sku,
                operation="both",
                status="blocked_listing_issue",
                product_type=product_type,
                marketplace_id=marketplace_id,
                request_payload={},
                response_body=body,
            )
            return {"sku": sku, "status": "blocked_listing_issue", "issues": len(issues)}

        patches = self._build_changed_patches(
            body=body,
            sku=sku,
            price=price,
            quantity=quantity,
            marketplace_id=marketplace_id,
        )
        if not patches:
            self._record(
                sku=sku,
                operation="none",
                status="skipped_no_change",
                product_type=product_type,
                marketplace_id=marketplace_id,
                request_payload={},
                response_body=body,
            )
            return {"sku": sku, "status": "skipped_no_change"}

        operation = self._operation_name(patches)
        request_payload = {"productType": product_type, "patches": patches}
        if dry_run:
            self._record(
                sku=sku,
                operation=operation,
                status="dry_run",
                product_type=product_type,
                marketplace_id=marketplace_id,
                request_payload=request_payload,
            )
            return {"sku": sku, "status": "dry_run"}

        try:
            response = client.patch_listings_item(
                sku=sku,
                product_type=product_type,
                patches=patches,
            )
        except Exception as exc:
            self._record(
                sku=sku,
                operation=operation,
                status="failed",
                product_type=product_type,
                marketplace_id=marketplace_id,
                request_payload=request_payload,
                error_message=str(exc),
            )
            return {"sku": sku, "status": "failed", "error": str(exc)}

        body = response.get("body", {})
        request_id = response.get("headers", {}).get("x-amzn-RequestId", "")
        patch_issues = body.get("issues") or []
        patch_status = body.get("status", "ACCEPTED")
        if patch_issues:
            status = "issues_found"
            issue_count = len(patch_issues)
            response_body = body
        elif patch_status != "ACCEPTED":
            status = "not_accepted"
            issue_count = 0
            response_body = body
        else:
            confirmation = self._confirm_update(client, sku, price, quantity)
            status = confirmation["status"]
            issue_count = confirmation.get("issues", 0)
            response_body = {
                "patch_response": body,
                "confirmation": confirmation,
            }

        self._record(
            sku=sku,
            operation=operation,
            status=status,
            amazon_request_id=request_id,
            product_type=product_type,
            marketplace_id=marketplace_id,
            request_payload=request_payload,
            response_body=response_body,
        )
        return {
            "sku": sku,
            "status": status,
            "request_id": request_id,
            "issues": issue_count,
        }

    def _confirm_update(
        self,
        client: Any,
        sku: str,
        target_price: Optional[float],
        target_quantity: Optional[int],
    ) -> Dict[str, Any]:
        current = self._get_listing_for_update(client, sku)
        if current["status"] != "found":
            return {
                "status": (
                    "accepted_pending_confirmation"
                    if current["status"] == "skipped_not_found"
                    else "confirmation_failed"
                ),
                "issues": 0,
                "body": current.get("body"),
                "error": current.get("error"),
            }
        body = current["body"]
        issues = body.get("issues") or []
        if issues:
            return {"status": "confirmed_with_issues", "issues": len(issues), "body": body}
        mismatches = self._target_mismatches(body, target_price, target_quantity)
        if mismatches:
            return {
                "status": "confirmed_with_mismatch",
                "issues": 0,
                "body": body,
                "mismatches": mismatches,
            }
        return {"status": "update_confirmed", "issues": 0, "body": body}

    def _get_listing_for_update(self, client: Any, sku: str) -> Dict[str, Any]:
        try:
            response = client.get_listings_item(sku=sku, included_data=self.INCLUDED_DATA)
            body = response.get("body", {})
            if body:
                self.cache_repo.upsert_items([body])
            return {"status": "found", "body": body}
        except AmazonAPIException as exc:
            if exc.status_code == 404:
                return {"status": "skipped_not_found", "body": None}
            return {"status": "failed_existing_check", "error": str(exc), "body": None}
        except Exception as exc:
            return {"status": "failed_existing_check", "error": str(exc), "body": None}

    def _build_changed_patches(
        self,
        body: Dict[str, Any],
        sku: str,
        price: Optional[float],
        quantity: Optional[int],
        marketplace_id: str,
    ) -> List[Dict[str, Any]]:
        patches = []
        current_price = self._extract_price(body)
        current_quantity = self._extract_quantity(body)
        if price is not None and not self._same_number(current_price, price):
            patches.extend(self._build_patches(sku, price, None, marketplace_id))
        if quantity is not None and current_quantity != int(quantity):
            patches.extend(self._build_patches(sku, None, quantity, marketplace_id))
        return patches

    @staticmethod
    def _build_patches(
        sku: str,
        price: Optional[float],
        quantity: Optional[int],
        marketplace_id: str,
    ) -> List[Dict[str, Any]]:
        from src.services.amz_inventory_price_updater_service import (
            InventoryPriceUpdaterService,
        )

        return InventoryPriceUpdaterService._build_patches(
            sku=sku,
            price=price,
            quantity=quantity,
            marketplace_id=marketplace_id,
        )

    def _target_mismatches(
        self,
        body: Dict[str, Any],
        price: Optional[float],
        quantity: Optional[int],
    ) -> Dict[str, Any]:
        mismatches: Dict[str, Any] = {}
        current_price = self._extract_price(body)
        current_quantity = self._extract_quantity(body)
        if price is not None and not self._same_number(current_price, price):
            mismatches["price"] = {"expected": float(price), "actual": current_price}
        if quantity is not None and current_quantity != int(quantity):
            mismatches["quantity"] = {
                "expected": int(quantity),
                "actual": current_quantity,
            }
        return mismatches

    @staticmethod
    def _extract_price(body: Dict[str, Any]) -> Optional[float]:
        for offer in body.get("offers") or []:
            for key in ("price", "listingPrice"):
                value = offer.get(key)
                if isinstance(value, dict):
                    amount = value.get("amount") or value.get("value")
                    if amount is not None:
                        return float(amount)
        try:
            schedule = (
                body["attributes"]["purchasable_offer"][0]["our_price"][0]["schedule"][0]
            )
            return float(schedule["value_with_tax"])
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _extract_quantity(body: Dict[str, Any]) -> Optional[int]:
        for item in body.get("fulfillmentAvailability") or []:
            if item.get("quantity") is not None:
                return int(item["quantity"])
        try:
            return int(
                body["attributes"]["fulfillment_availability"][0]["quantity"]
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _product_type(body: Dict[str, Any], item: Dict[str, Any]) -> str:
        summaries = body.get("summaries") or []
        if summaries and summaries[0].get("productType"):
            return summaries[0]["productType"]
        product_types = body.get("productTypes") or []
        if product_types and product_types[0].get("productType"):
            return product_types[0]["productType"]
        return item.get("product_type") or "PRODUCT"

    @staticmethod
    def _has_blocking_issues(issues: List[Dict[str, Any]]) -> bool:
        return any(str(issue.get("severity", "")).upper() == "ERROR" for issue in issues)

    @staticmethod
    def _operation_name(patches: List[Dict[str, Any]]) -> str:
        paths = {patch["path"] for patch in patches}
        has_price = "/attributes/purchasable_offer" in paths
        has_quantity = "/attributes/fulfillment_availability" in paths
        if has_price and has_quantity:
            return "both"
        if has_price:
            return "price"
        if has_quantity:
            return "quantity"
        return "none"

    @staticmethod
    def _same_number(left: Optional[float], right: float) -> bool:
        if left is None:
            return False
        return round(float(left), 2) == round(float(right), 2)

    @staticmethod
    def _next_page_token(body: Dict[str, Any]) -> Optional[str]:
        pagination = body.get("pagination") or {}
        return pagination.get("nextToken") or pagination.get("nextPageToken")

    def _record(self, **kwargs) -> None:
        self.submission_repo.insert_submission(**kwargs)

    def _listings_client(self):
        if self._listings_client_instance is not None:
            return self._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self._listings_client_instance = AmazonListingsClient()
        return self._listings_client_instance

    def _emit_summary(self, results: List[Dict[str, Any]]) -> None:
        success_count = sum(
            1 for item in results
            if item["status"] in ("dry_run", "update_confirmed", "skipped_no_change")
        )
        fail_count = sum(1 for item in results if item["status"] == "failed")
        self.reporter.emit(f"\n{'=' * 70}")
        self.reporter.emit(f"API Update Complete: {len(results)} SKUs processed")
        self.reporter.emit(f"  Success / Dry-run / No-change: {success_count}")
        self.reporter.emit(f"  Failed: {fail_count}")
        self.reporter.emit(f"{'=' * 70}")
