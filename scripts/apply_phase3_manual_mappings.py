#!/usr/bin/env python3
"""Apply Phase 3 manual supplier category -> Amazon product type mappings."""

from __future__ import annotations

from infrastructure.db_pool import SessionLocal
from src.repositories.category_repository import CategoryRepository
from src.services.amazon_schema_service import AmazonSchemaService

# Pending-pool UNMAPPED supplier categories (30 SKUs / 10 codes).
# Rationale documented in docs/test-reports/2026-06-28-phase3-manual-mappings.md
PHASE3_MAPPINGS = [
    ("10019", "MAKEUP_VANITY"),      # 12 vanity desks / LED mirrors
    ("10031", "CABINET"),            # 5 TV entertainment wall units
    ("10006", "RIDE_ON_TOY"),        # 4 kids ride-on cars / scooters
    ("10051", "FURNITURE"),          # 2 kitchen islands
    ("10145", "OUTDOOR_LIVING"),      # 2 infrared saunas (SAUNA PT unsupported for seller)
    ("10107", "ARTIFICIAL_TREE"),    # 1 pre-lit Christmas set
    ("10149", "FURNITURE"),          # 1 laundry countertop
    ("10159", "TABLE"),              # 1 picnic table
    ("10165", "FIRE_PIT"),           # 1 propane fire pit table
    ("10931", "CABINET"),            # 1 metal storage cabinet
]


def main() -> None:
    updates = [
        {
            "supplier_platform": "giga",
            "supplier_category_code": code,
            "standard_category_name": product_type,
        }
        for code, product_type in PHASE3_MAPPINGS
    ]
    with SessionLocal() as db:
        repo = CategoryRepository(db)
        count = repo.batch_update_category_mappings(updates)
        print(f"Updated {count} supplier category mappings")
        schema = AmazonSchemaService(db)
        for _, product_type in PHASE3_MAPPINGS:
            try:
                schema.fetch_and_cache(product_type)
                print(f"  schema cached: {product_type}")
            except Exception as exc:
                print(f"  schema cache FAILED {product_type}: {exc}")


if __name__ == "__main__":
    main()
