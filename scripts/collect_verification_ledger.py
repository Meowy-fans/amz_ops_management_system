#!/usr/bin/env python3
"""Collect latest verification status per SKU from amazon_api_submissions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import text

from infrastructure.db_pool import SessionLocal

INVENTORY = Path("docs/test-reports/2026-06-28-pending-verification-inventory.json")


def terminal_state(status: str) -> str:
    mapping = {
        "validation_preview_passed": "PASS",
        "validation_preview_issues": "PASS-WARN/ISSUES",
        "needs_review": "BLOCK-REVIEW",
        "blocked_attribute_coverage": "BLOCK-ENGINE",
        "blocked_variation_resolution": "BLOCK-VARIATION",
        "blocked_commercial_gate": "BLOCK-COMMERCIAL",
        "skipped_existing_scope": "SKIP-EXISTING",
        "skipped_existing": "SKIP-EXISTING",
    }
    return mapping.get(status, status or "PENDING")


def main() -> int:
    inv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else INVENTORY
    inventory = json.loads(inv_path.read_text(encoding="utf-8"))
    all_skus: list[tuple[str, str]] = []
    for cat, block in inventory["categories"].items():
        for sku in block["skus"]:
            all_skus.append((cat, sku))
    query = text(
        """
        SELECT DISTINCT ON (sku)
               sku, status, product_type, submitted_at,
               response_body->'issues'->0->>'code' AS issue_code
        FROM amazon_api_submissions
        WHERE sku = ANY(:skus)
        ORDER BY sku, id DESC
        """
    )
    sku_list = [sku for _, sku in all_skus]
    with SessionLocal() as db:
        rows = {
            row["sku"]: dict(row)
            for row in db.execute(query, {"skus": sku_list}).mappings().all()
        }
    summary: dict[str, dict] = {}
    counts: dict[str, int] = {}
    ledger = []
    for cat, sku in all_skus:
        row = rows.get(sku)
        status = row["status"] if row else None
        terminal = terminal_state(status) if status else "PENDING"
        counts[terminal] = counts.get(terminal, 0) + 1
        summary.setdefault(cat, {}).setdefault(terminal, 0)
        summary[cat][terminal] = summary[cat].get(terminal, 0) + 1
        ledger.append(
            {
                "category": cat,
                "sku": sku,
                "status": status,
                "terminal": terminal,
                "issue_code": row.get("issue_code") if row else None,
                "submitted_at": str(row.get("submitted_at")) if row else None,
            }
        )
    out = {
        "inventory_total": inventory["total"],
        "ledger_rows": len(ledger),
        "terminal_counts": counts,
        "by_category": summary,
        "ledger": ledger,
    }
    out_path = inv_path.with_name("2026-06-28-pending-verification-ledger.json")
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print("terminal_counts", counts)
    for cat in sorted(summary):
        print(f"  {cat}: {summary[cat]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
