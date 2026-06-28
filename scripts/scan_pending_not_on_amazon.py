#!/usr/bin/env python3
"""Scan locally eligible Giga SKUs and group by category vs live Amazon existence."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict

from infrastructure.amazon.api_client import AmazonAPIException
from infrastructure.amazon.listings_client import AmazonListingsClient
from infrastructure.db_pool import SessionLocal
from sqlalchemy import text

PENDING_SQL = text(
    """
WITH pending AS (
    SELECT DISTINCT m.meow_sku
    FROM meow_sku_map m
    JOIN giga_product_sync_records psr
      ON m.vendor_sku = psr.giga_sku AND m.vendor_source = 'giga'
    JOIN giga_product_base_prices pbp ON m.vendor_sku = pbp.giga_sku
    WHERE psr.is_oversize IS NOT TRUE
      AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'
      AND pbp.sku_available IS TRUE
)
SELECT p.meow_sku,
       scm.standard_category_name,
       scm.supplier_category_code,
       scm.supplier_category_name,
       CASE WHEN cache.sku IS NULL THEN false ELSE true END AS in_cache
FROM pending p
JOIN meow_sku_map m ON m.meow_sku = p.meow_sku AND m.vendor_source = 'giga'
JOIN giga_product_sync_records psr ON m.vendor_sku = psr.giga_sku
LEFT JOIN supplier_categories_map scm
  ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
 AND scm.supplier_platform = 'giga'
LEFT JOIN amazon_listing_items_cache cache ON cache.sku = p.meow_sku
ORDER BY p.meow_sku
"""
)


def main() -> int:
    client = AmazonListingsClient()
    with SessionLocal() as db:
        rows = db.execute(PENDING_SQL).fetchall()

    cache_miss = [row for row in rows if not row.in_cache]
    print(
        f"pending_total={len(rows)} cache_miss={len(cache_miss)}",
        file=sys.stderr,
        flush=True,
    )

    by_cat: dict[str, dict] = defaultdict(
        lambda: {
            "not_on_amazon": [],
            "on_amazon": [],
            "check_failed": [],
            "supplier_codes": set(),
        }
    )

    for index, row in enumerate(cache_miss, start=1):
        sku = row.meow_sku
        raw_cat = (row.standard_category_name or "(未映射)").strip()
        cat = raw_cat.upper() if raw_cat != "(未映射)" else raw_cat
        if row.supplier_category_code:
            by_cat[cat]["supplier_codes"].add(
                f"{row.supplier_category_code}:{row.supplier_category_name}"
            )
        try:
            client.get_listings_item(sku=sku, included_data=["summaries"])
            by_cat[cat]["on_amazon"].append(sku)
        except AmazonAPIException as exc:
            if exc.status_code == 404:
                by_cat[cat]["not_on_amazon"].append(sku)
            else:
                by_cat[cat]["check_failed"].append({"sku": sku, "error": str(exc)})
        except Exception as exc:  # pragma: no cover - operational script
            by_cat[cat]["check_failed"].append({"sku": sku, "error": str(exc)})

        if index % 15 == 0:
            print(f"checked {index}/{len(cache_miss)}", file=sys.stderr, flush=True)
            time.sleep(0.15)

    summary = []
    for cat in sorted(
        by_cat.keys(),
        key=lambda name: (-len(by_cat[name]["not_on_amazon"]), name),
    ):
        bucket = by_cat[cat]
        summary.append(
            {
                "category": cat,
                "not_on_amazon_count": len(bucket["not_on_amazon"]),
                "actually_on_amazon_count": len(bucket["on_amazon"]),
                "check_failed_count": len(bucket["check_failed"]),
                "supplier_category_hints": sorted(bucket["supplier_codes"]),
                "not_on_amazon_skus": bucket["not_on_amazon"],
                "on_amazon_skus": bucket["on_amazon"],
                "check_failed": bucket["check_failed"],
            }
        )

    print(json.dumps({"summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
