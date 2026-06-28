#!/usr/bin/env python3
"""Run V2 strict preview for Phase 3 manual-mapped pending SKUs."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from infrastructure.db_pool import SessionLocal
from src.services.product_listing_api_plan_builder import ProductListingAPIPlanBuilder
from src.services.product_listing_service import ProductListingService
from src.services.validation_preview_v2 import ValidationPreviewV2

PHASE3_CODES = [
    "10019",
    "10031",
    "10006",
    "10051",
    "10145",
    "10107",
    "10149",
    "10159",
    "10165",
    "10931",
]

QUERY = text(
    """
    SELECT DISTINCT m.meow_sku, UPPER(scm.standard_category_name) AS product_type
    FROM supplier_categories_map scm
        JOIN giga_product_sync_records psr
            ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
        JOIN meow_sku_map m
            ON m.vendor_sku = psr.giga_sku AND m.vendor_source = 'giga'
        JOIN giga_product_base_prices pbp ON pbp.giga_sku = psr.giga_sku
        LEFT JOIN amz_all_listing_report r ON r."seller-sku" = m.meow_sku
    WHERE scm.supplier_platform = 'giga'
      AND scm.supplier_category_code = ANY(:codes)
      AND psr.is_oversize IS NOT TRUE
      AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'
      AND pbp.sku_available IS TRUE
      AND r."seller-sku" IS NULL
    ORDER BY 2, 1
    """
)

OUT_PATH = Path("docs/test-reports/2026-06-28-phase3-strict-preview.json")


def main() -> int:
    results: list[dict] = []
    by_cat: dict[str, list[dict]] = defaultdict(list)
    with SessionLocal() as db:
        rows = db.execute(QUERY, {"codes": PHASE3_CODES}).fetchall()
        svc = ProductListingService(db=db)
        svc.listing_payload_engine_mode = "v2"
        builder = ProductListingAPIPlanBuilder(svc)
        previewer = ValidationPreviewV2(db=db)
        for sku, cat in rows:
            try:
                plan = builder.build_v2_payload_plan_for_sku(cat, sku)
                blocked = getattr(plan, "blocked_reason", None)
                if blocked:
                    status = str(blocked)
                    issues: list = []
                else:
                    preview = previewer.preview(plan)
                    status = preview.status
                    issues = preview.issues or []
            except Exception as exc:
                status = f"error:{type(exc).__name__}"
                issues = [str(exc)]
            entry = {
                "sku": sku,
                "category": cat,
                "status": status,
                "issue_count": len(issues),
                "top_issue": issues[0] if issues else None,
            }
            results.append(entry)
            by_cat[cat].append(entry)
            print(f"{cat}\t{sku}\t{status}\t{len(issues)}")

    summary = {}
    for cat, items in sorted(by_cat.items()):
        passed = sum(1 for item in items if item["status"] == "validation_preview_passed")
        issues = sum(1 for item in items if item["status"] == "validation_preview_issues")
        blocked = sum(
            1
            for item in items
            if item["status"] not in ("validation_preview_passed", "validation_preview_issues")
        )
        summary[cat] = {
            "total": len(items),
            "passed": passed,
            "issues": issues,
            "blocked": blocked,
        }

    payload = {"total": len(results), "summary": summary, "results": results}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("--- SUMMARY ---")
    for cat, stats in summary.items():
        print(
            f"{cat}: {stats['passed']}/{stats['total']} passed, "
            f"{stats['issues']} issues, {stats['blocked']} blocked"
        )
    total_passed = sum(stats["passed"] for stats in summary.values())
    print(f"TOTAL: {total_passed}/{len(results)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
