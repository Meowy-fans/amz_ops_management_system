#!/usr/bin/env python3
"""Regenerate and validate compliance-safe listing content for explicit vendor SKUs."""
import json
import sys

from sqlalchemy import text

from infrastructure.db_pool import SessionLocal
from src.services.compliance_claim_scanner import ComplianceClaimScanner
from src.services.product_detail_generation_service import ProductDetailGenerationService

VENDOR_SKUS = [
    "W2615S00095",
    "W3151S00044",
    "W1865S00171",
    "W3151S00046",
    "W3136S00021",
    "N710S324097B",
]


def main() -> int:
    skus = sys.argv[1:] or VENDOR_SKUS
    scanner = ComplianceClaimScanner()

    with SessionLocal() as db:
        service = ProductDetailGenerationService(db=db)
        saved = service.process_skus(skus)

    print(f"\nSaved {saved}/{len(skus)} regenerated SKU(s)")
    failures = []
    for sku in skus:
        with SessionLocal() as db:
            row = db.execute(
                text("""
                SELECT product_name, selling_point_1, selling_point_2, selling_point_3,
                       selling_point_4, selling_point_5, product_description, raw_json
                FROM ds_api_product_details
                WHERE sku_id = :sku
                """),
                {"sku": sku},
            ).fetchone()
        if not row:
            failures.append((sku, "missing regenerated row"))
            continue
        raw_json = row[7] if isinstance(row[7], dict) else json.loads(row[7] or "{}")
        fields = {
            "title": row[0],
            "bullet_1": row[1] or "",
            "bullet_2": row[2] or "",
            "bullet_3": row[3] or "",
            "bullet_4": row[4] or "",
            "bullet_5": row[5] or "",
            "description": row[6] or "",
            "search_terms": raw_json.get("search_terms", ""),
            "generic_keyword": raw_json.get("generic_keyword", ""),
        }
        hits = scanner.scan_fields(fields)
        status = "PASS" if not hits else "FAIL"
        print(f"  [{status}] {sku}")
        if hits:
            failures.append((sku, [hit.matched_text for hit in hits]))
        if raw_json.get("compliance_blocked"):
            failures.append((sku, "compliance_blocked in raw_json"))
        if raw_json.get("auto_sanitized"):
            print(f"         auto_sanitized fixes={len(raw_json.get('compliance_fixes', []))}")

    if failures:
        print("\nCompliance acceptance failed:")
        for sku, detail in failures:
            print(f"  - {sku}: {detail}")
        return 1

    print("\nCompliance acceptance passed for all SKUs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
