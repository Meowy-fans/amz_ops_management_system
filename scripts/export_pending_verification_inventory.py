#!/usr/bin/env python3
"""Export pending listing verification inventory (offline-report-miss pool)."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from infrastructure.db_pool import SessionLocal
from src.repositories.product_listing_repository import ProductListingRepository
from src.services.category_readiness_service import CategoryReadinessService
from src.utils.variation_helper import VariationHelper

PENDING_QUERY = text(
    """
    SELECT DISTINCT m.meow_sku,
           COALESCE(NULLIF(UPPER(scm.standard_category_name), ''), 'UNMAPPED') AS product_type
    FROM supplier_categories_map scm
        JOIN giga_product_sync_records psr
            ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
        JOIN meow_sku_map m
            ON m.vendor_sku = psr.giga_sku AND m.vendor_source = 'giga'
        JOIN giga_product_base_prices pbp ON pbp.giga_sku = psr.giga_sku
        LEFT JOIN amz_all_listing_report r ON r."seller-sku" = m.meow_sku
    WHERE scm.supplier_platform = 'giga'
      AND psr.is_oversize IS NOT TRUE
      AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'
      AND pbp.sku_available IS TRUE
      AND r."seller-sku" IS NULL
    ORDER BY 2, 1
    """
)


def main() -> int:
    out_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "docs/test-reports/2026-06-28-pending-verification-inventory.json"
    )
    with SessionLocal() as db:
        rows = db.execute(PENDING_QUERY).fetchall()
        readiness = {
            item.product_type: item.as_dict()
            for item in CategoryReadinessService(db).list_readiness()
        }
        repo = ProductListingRepository(db)
        helper = VariationHelper()
        by_cat: dict[str, list[str]] = defaultdict(list)
        for sku, cat in rows:
            by_cat[str(cat)].append(str(sku))
        inventory: dict[str, dict] = {}
        for cat in sorted(by_cat, key=lambda name: (-len(by_cat[name]), name)):
            skus = sorted(by_cat[cat])
            singles, families = helper.find_variation_families(repo.get_variation_data(skus))
            inventory[cat] = {
                "count": len(skus),
                "readiness": readiness.get(cat, {}),
                "skus": skus,
                "singles": singles,
                "families": families,
            }
        payload = {
            "total": len(rows),
            "pool": "offline_report_miss",
            "categories": inventory,
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out_path} total={payload['total']}")
    for cat, block in inventory.items():
        mode = block["readiness"].get("rule_mode", "?")
        status = block["readiness"].get("status", "?")
        print(f"  {cat}: {block['count']} mode={mode} status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
