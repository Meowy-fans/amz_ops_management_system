#!/usr/bin/env python3
"""S6 golden regression runner for Listing Rule Authoring V2."""

from __future__ import annotations

import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from infrastructure.db_pool import SessionLocal
from src.services.amazon_schema_service import AmazonSchemaService
from src.services.rule_migration_v2 import RuleMigrationV2


def main() -> int:
    with SessionLocal() as db:
        migrator = RuleMigrationV2(schema_service=AmazonSchemaService(db))
        report = migrator.evaluate_golden_regression(db)
        payload = report.as_dict()
        payload["migrations"] = [
            migrator.migrate_product_type(case.product_type).as_dict()
            for case in RuleMigrationV2.DEFAULT_GOLDEN_CASES
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if report.status == "go" else 1


if __name__ == "__main__":
    raise SystemExit(main())
