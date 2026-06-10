"""PATCH item_package_dimensions / weight / quantity for combo products from Giga data."""

import logging
from typing import Any, Dict, List, Optional

from src.services.progress_reporter import ProgressReporter
from src.repositories.amazon_api_submission_repository import (
    AmazonAPISubmissionRepository,
)

logger = logging.getLogger(__name__)


class AmazonPackageDimensionsService:
    """Builds and submits package-dimension patches for combo (multi-box) listings."""

    def __init__(
        self,
        db,
        reporter: Optional[ProgressReporter] = None,
        listings_client: Any = None,
        submission_repo: Any = None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self.submission_repo = submission_repo or AmazonAPISubmissionRepository(db)

    def submit_package_dimensions(
        self,
        dry_run: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """For every combo listing missing package dimensions, build and submit patches."""
        candidates = self._get_combo_candidates(limit=limit)
        if not candidates:
            self.reporter.emit("No combo products missing package dimensions.")
            return []

        client = self._listings_client()
        results = []
        for item in candidates:
            result = self._process_one(client, item, dry_run)
            if result is not None:
                results.append(result)

        self._emit_summary(results)
        return results

    def _get_combo_candidates(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        from sqlalchemy import text

        query = """
            WITH latest_record AS (
                SELECT DISTINCT ON (giga_sku)
                    giga_sku, raw_data
                FROM giga_product_sync_records
                ORDER BY giga_sku, id DESC
            )
            SELECT
                m.meow_sku,
                m.vendor_sku,
                lr.raw_data->'comboInfo' AS combo_info,
                lr.raw_data->>'lengthUnit' AS dim_unit,
                cache.attributes->'item_package_dimensions' IS NULL AS need_pkg_dims,
                cache.attributes->'item_package_weight' IS NULL AS need_pkg_wt,
                cache.attributes->'item_package_quantity' IS NULL AS need_pkg_qty,
                cache.attributes->'number_of_items' IS NULL AS need_num_items,
                (cache.attributes->'productTypes'->0->>'productType') AS active_pt,
                COALESCE(
                    cache.attributes->'summaries'->0->>'productType',
                    cache.attributes->'productTypes'->0->>'productType',
                    'PRODUCT'
                ) AS product_type,
                cache.attributes->'item_package_dimensions' AS current_pkg_dims,
                cache.attributes->'item_package_weight' AS current_pkg_wt,
                cache.attributes->'item_package_quantity' AS current_pkg_qty
            FROM amazon_listing_items_cache cache
            JOIN meow_sku_map m ON cache.sku = m.meow_sku
            JOIN latest_record lr ON lr.giga_sku = m.vendor_sku
            WHERE lr.raw_data->>'comboFlag' = 'true'
              AND jsonb_array_length(lr.raw_data->'comboInfo') > 0
              AND (
                  cache.attributes->'item_package_dimensions' IS NULL
                  OR cache.attributes->'item_package_weight' IS NULL
                  OR cache.attributes->'item_package_quantity' IS NULL
              )
            ORDER BY m.meow_sku
        """
        if limit:
            query += f" LIMIT {int(limit)}"

        rows = self.db.execute(text(query)).mappings()
        return [dict(row) for row in rows]

    def _process_one(
        self,
        client: Any,
        item: Dict[str, Any],
        dry_run: bool,
    ) -> Optional[Dict[str, Any]]:
        sku = item["meow_sku"]
        combo_info = item["combo_info"] or []
        if isinstance(combo_info, str):
            import json
            combo_info = json.loads(combo_info)
        if not combo_info:
            return None

        patches = self._build_patches(combo_info, item)
        if not patches:
            self.reporter.emit(f"  SKIP {sku}: no patches needed")
            return None

        product_type = item.get("product_type") or "PRODUCT"
        marketplace_id = item.get(
            "marketplace_id",
            "ATVPDKIKX0DER",
        )
        request_payload = {
            "productType": product_type,
            "patches": patches,
        }

        if dry_run:
            self.submission_repo.insert_submission(
                sku=sku,
                operation="package_dimensions",
                status="dry_run",
                product_type=product_type,
                request_payload=request_payload,
            )
            return {"sku": sku, "status": "dry_run", "patches": len(patches)}

        try:
            response = client.patch_listings_item(
                sku=sku,
                product_type=product_type,
                patches=patches,
            )
            body = response.get("body", {})
            issues = body.get("issues") or []
            patch_status = body.get("status", "ACCEPTED")
            blocking = [i for i in issues if str(i.get("severity", "")).upper() == "ERROR"]
            if blocking:
                status = "issues_found"
            elif issues:
                status = "submitted"  # WARNING only, submission accepted
            elif patch_status != "ACCEPTED":
                status = "not_accepted"
            else:
                status = "submitted"
            self.submission_repo.insert_submission(
                sku=sku,
                operation="package_dimensions",
                status=status,
                product_type=product_type,
                request_payload=request_payload,
                response_body=body,
            )
            return {
                "sku": sku,
                "status": status,
                "patches": len(patches),
                "issues": len(issues),
            }
        except Exception as exc:
            self.submission_repo.insert_submission(
                sku=sku,
                operation="package_dimensions",
                status="failed",
                product_type=product_type,
                request_payload=request_payload,
                error_message=str(exc),
            )
            return {"sku": sku, "status": "failed", "error": str(exc)}

    @staticmethod
    def _build_patches(
        combo_info: List[Dict[str, Any]],
        item: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Build JSON Patch operations for package attributes from Giga comboInfo."""
        patches = []
        marketplace_id = "ATVPDKIKX0DER"

        # Find the largest package by volume for item_package_dimensions
        largest = None
        largest_vol = -1
        total_weight = 0.0
        for box in combo_info:
            l = float(box.get("length") or 0)
            w = float(box.get("width") or 0)
            h = float(box.get("height") or 0)
            weight = float(box.get("weight") or 0)
            total_weight += weight
            vol = l * w * h
            if vol > largest_vol:
                largest_vol = vol
                largest = box

        if largest is None:
            return patches

        # item_package_dimensions — largest box, always inches
        if item.get("need_pkg_dims", True):
            patches.append({
                "op": "add",
                "path": "/attributes/item_package_dimensions",
                "value": [{
                    "marketplace_id": marketplace_id,
                    "length": {
                        "value": round(float(largest.get("length", 0)), 2),
                        "unit": "inches",
                    },
                    "width": {
                        "value": round(float(largest.get("width", 0)), 2),
                        "unit": "inches",
                    },
                    "height": {
                        "value": round(float(largest.get("height", 0)), 2),
                        "unit": "inches",
                    },
                }],
            })

        # item_package_weight — total of all boxes
        if item.get("need_pkg_wt", True):
            patches.append({
                "op": "add",
                "path": "/attributes/item_package_weight",
                "value": [{
                    "value": round(total_weight, 2),
                    "unit": "pounds",
                }],
            })

        # item_package_quantity — number of boxes
        if item.get("need_pkg_qty", True):
            patches.append({
                "op": "add",
                "path": "/attributes/item_package_quantity",
                "value": [{
                    "value": len(combo_info),
                }],
            })

        # number_of_items — always 1 for a combo product (one selling unit)
        if item.get("need_num_items", True):
            patches.append({
                "op": "add",
                "path": "/attributes/number_of_items",
                "value": [{
                    "value": 1,
                    "marketplace_id": marketplace_id,
                }],
            })

        return patches

    def _listings_client(self):
        if self._listings_client_instance is not None:
            return self._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self._listings_client_instance = AmazonListingsClient()
        return self._listings_client_instance

    def _emit_summary(self, results: List[Dict[str, Any]]) -> None:
        counts: Dict[str, int] = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        total_patches = sum(r.get("patches", 0) for r in results)
        self.reporter.emit(f"\n{'=' * 70}")
        self.reporter.emit(f"Package Dimensions Update: {len(results)} SKUs, {total_patches} patches")
        for status, count in sorted(counts.items()):
            self.reporter.emit(f"  {status}: {count}")
        self.reporter.emit(f"{'=' * 70}")
