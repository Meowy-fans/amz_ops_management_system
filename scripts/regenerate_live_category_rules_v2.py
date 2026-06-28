#!/usr/bin/env python3
"""Backup live_eligible rules and regenerate V2 onboarded drafts in a side directory."""

from __future__ import annotations

import copy
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from infrastructure.db_pool import SessionLocal
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.category_onboarding_v2 import CategoryOnboardingV2
from src.services.rule_migration_v2 import ROOT_LEGACY_OVERRIDE_KEYS

RULES_ROOT = (
    project_root / "config" / "amz_listing_data_mapping" / "api_attribute_rules"
)
BACKUP_DIR = RULES_ROOT / "backups" / "live_eligible_2026-06-28"
OUTPUT_DIR = RULES_ROOT / "v2_onboarded"
REPORT_DIR = project_root / "docs" / "test-reports"

# product_type -> reference for pattern reuse
REGENERATE_PLAN: Dict[str, Optional[str]] = {
    "CABINET": "TABLE",
    "HOME_MIRROR": "CABINET",
    "SOFA": "TABLE",
    "OTTOMAN": "SOFA",
}


def _load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def backup_live_rules(categories: List[str]) -> Dict[str, str]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backed: Dict[str, str] = {}
    canonical = AttributeRuleLoader()
    for category in categories:
        name = category.lower()
        src = canonical.config_dir / f"{name}.yaml"
        if not src.exists():
            raise FileNotFoundError(f"Missing live rule file: {src}")
        dst = BACKUP_DIR / f"{name}.yaml"
        shutil.copy2(src, dst)
        backed[category] = str(dst)
    return backed


def merge_operator_root_keys(
    generated: Dict[str, Any],
    legacy: Dict[str, Any],
    *,
    category: str,
) -> Dict[str, Any]:
    """Keep operator-tuned root config from live backup on top of V2 draft."""
    merged = copy.deepcopy(generated)
    merged["mode"] = AttributeRuleLoader.DEFAULT_MODE
    for key in ROOT_LEGACY_OVERRIDE_KEYS:
        if key == "mode":
            continue
        if key in legacy and legacy[key] is not None:
            merged[key] = copy.deepcopy(legacy[key])
    merged["generated_from"] = "regenerate_live_category_rules_v2"
    merged["regenerated_from_backup"] = str(BACKUP_DIR / f"{category.lower()}.yaml")
    return merged


def regenerate_category(
    category: str,
    *,
    reference: Optional[str],
    sample_sku_limit: int = 4,
) -> Dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"{category.lower()}.yaml"
    legacy = _load_yaml(backup_path)

    draft_loader = AttributeRuleLoader(config_dir=OUTPUT_DIR)
    with SessionLocal() as db:
        report = CategoryOnboardingV2(db=db, rule_loader=draft_loader).onboard(
            category,
            reference_product_type=reference,
            sample_sku_limit=sample_sku_limit,
            overwrite_skeleton=True,
            run_s7_offline=True,
            run_s7_preview=False,
        )

    draft_path = OUTPUT_DIR / f"{category.lower()}.yaml"
    generated = _load_yaml(draft_path)
    merged = merge_operator_root_keys(generated, legacy, category=category)
    draft_path.write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    return {
        "product_type": category,
        "reference": reference,
        "backup_path": str(backup_path),
        "draft_path": str(draft_path),
        "onboard_status": report.status,
        "pool_skus": report.pool_skus,
        "review_blocking_count": report.review_blocking_count,
        "acceptance_report_path": report.acceptance_report_path,
        "state_path": report.state_path,
        "legacy_mode": legacy.get("mode"),
        "draft_mode": merged.get("mode"),
        "legacy_attribute_count": len(legacy.get("attributes") or {}),
        "draft_attribute_count": len(merged.get("attributes") or {}),
        "steps": [step.as_dict() for step in report.steps],
    }


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    categories = list(REGENERATE_PLAN.keys())
    summary: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backup_dir": str(BACKUP_DIR),
        "output_dir": str(OUTPUT_DIR),
        "categories": {},
    }

    print(f"Backing up live_eligible rules -> {BACKUP_DIR}")
    summary["backups"] = backup_live_rules(categories)

    for category, reference in REGENERATE_PLAN.items():
        print(f"\n=== Regenerating {category} (reference={reference}) ===")
        result = regenerate_category(category, reference=reference)
        summary["categories"][category] = result
        print(
            f"draft={result['draft_path']} "
            f"attrs {result['legacy_attribute_count']} -> {result['draft_attribute_count']} "
            f"blocking={result['review_blocking_count']}"
        )

    README = OUTPUT_DIR / "README.md"
    README.write_text(
        """# V2 Onboarded Rule Drafts (live categories)

Side-by-side V2 rule drafts for **CABINET / HOME_MIRROR / SOFA / OTTOMAN**.

- **Do not use for LIVE submit** until reviewed, S7 passed, and promoted via `promote-category-rules-v2`.
- Canonical `live_eligible` rules remain in the parent directory; backups under `backups/live_eligible_2026-06-28/`.
- Generated by `scripts/regenerate_live_category_rules_v2.py` (onboard-category-v2 pipeline, `mode: dry_run`).

Load drafts for acceptance:

```bash
# Example: point loader at v2_onboarded when running offline S7 / review
python3 scripts/s7_rule_authoring_acceptance.py CABINET  # uses canonical by default;
# use regenerate script report or custom loader for draft comparison
```
""",
        encoding="utf-8",
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{stamp}-live-categories-v2-regenerate.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
