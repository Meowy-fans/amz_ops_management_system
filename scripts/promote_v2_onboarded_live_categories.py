#!/usr/bin/env python3
"""Recertify live golden categories: backup -> v2_onboarded -> review -> promote -> retire.

Run offline/review on host DB; run preview+promote inside production container
(Amazon SP-API credentials required).
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from infrastructure.db_pool import SessionLocal
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.category_rule_promotion_v2 import CategoryRulePromotionV2
from src.services.rule_migration_v2 import RuleMigrationV2
from src.services.rule_review_service_v2 import RuleReviewServiceV2
from src.services.rule_yaml_write_guard import write_rule_yaml
from src.services.amazon_schema_service import AmazonSchemaService

RULES_ROOT = project_root / "config" / "amz_listing_data_mapping" / "api_attribute_rules"
LIVE_BACKUP = RULES_ROOT / "backups" / "live_eligible_2026-06-28"
DRAFT_DIR = RULES_ROOT / "v2_onboarded"
RETIRED_DIR = RULES_ROOT / "backups" / "retired_pre_v2_onboard_2026-06-28"
REPORT_DIR = project_root / "docs" / "test-reports"

CATEGORIES = ["CABINET", "HOME_MIRROR", "SOFA", "OTTOMAN"]
GOLDEN_SKUS = {
    "CABINET": "meow251115FC0ie",
    "HOME_MIRROR": "meow251108CqW5i",
    "SOFA": "meow25110865jrz",
    "OTTOMAN": "meow2511088jSUW",
}
REVIEWER = "cursor@v2-onboard-promote"
STAMP = "2026-06-28"
CONTAINER = "amz-listing-management-system"


def load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def prepare_drafts() -> None:
    for category in CATEGORIES:
        legacy = load_yaml(LIVE_BACKUP / f"{category.lower()}.yaml")
        rules = copy.deepcopy(legacy)
        rules["mode"] = AttributeRuleLoader.DEFAULT_MODE
        rules["version"] = f"{category.lower()}_v2_onboarded_{STAMP}"
        write_rule_yaml(
            DRAFT_DIR / f"{category.lower()}.yaml",
            rules,
            product_type=category,
            written_by="v2_onboard_live_recertify",
        )


def stage_to_canonical() -> None:
    RETIRED_DIR.mkdir(parents=True, exist_ok=True)
    for category in CATEGORIES:
        canonical = RULES_ROOT / f"{category.lower()}.yaml"
        if canonical.exists():
            shutil.copy2(canonical, RETIRED_DIR / f"{category.lower()}.yaml")
        rules = load_yaml(DRAFT_DIR / f"{category.lower()}.yaml")
        rules["mode"] = AttributeRuleLoader.DEFAULT_MODE
        write_rule_yaml(
            canonical,
            rules,
            product_type=category,
            written_by="v2_onboard_staging_for_promote",
        )


def host_precheck() -> Dict[str, Any]:
    summary: Dict[str, Any] = {"categories": {}}
    with SessionLocal() as db:
        for category in CATEGORIES:
            loader = AttributeRuleLoader(config_dir=DRAFT_DIR)
            review = RuleReviewServiceV2(rule_loader=loader).review_category(category, db=db)
            if review.blocking_item_count:
                raise RuntimeError(f"{category}: {review.blocking_item_count} blocking items")
            promo = CategoryRulePromotionV2()
            offline = promo._offline_summary(db, category, acceptance_data=None)
            summary["categories"][category] = {"offline": offline}
            if offline["sku_count"] and offline["zero_missing"] < offline["sku_count"]:
                raise RuntimeError(f"{category} offline regression")
    return summary


def docker_cp_rules() -> None:
    for category in CATEGORIES:
        src = RULES_ROOT / f"{category.lower()}.yaml"
        dst = (
            f"{CONTAINER}:/app/config/amz_listing_data_mapping/api_attribute_rules/"
            f"{category.lower()}.yaml"
        )
        subprocess.run(["docker", "cp", str(src), dst], check=True)


def docker_promote_all() -> None:
    golden_map = " ".join(f"{k}={v}" for k, v in GOLDEN_SKUS.items())
    script = f"""
set -e
declare -A GOLDEN
{chr(10).join(f'GOLDEN[{k}]={v}' for k, v in GOLDEN_SKUS.items())}
for CAT in {' '.join(CATEGORIES)}; do
  GOLD=${{GOLDEN[$CAT]}}
  python3 << 'PY'
import json
from pathlib import Path
from infrastructure.db_pool import SessionLocal
from src.services.amazon_schema_service import AmazonSchemaService
from src.services.category_rule_promotion_v2 import CategoryRulePromotionV2
from src.services.rule_migration_v2 import RuleMigrationV2
from src.services.product_listing_service import ProductListingService
from src.services.product_listing_api_plan_builder import ProductListingAPIPlanBuilder
from src.services.validation_preview_v2 import ValidationPreviewV2

cat = "$CAT"
golden = "$GOLD"
with SessionLocal() as db:
    promo = CategoryRulePromotionV2(migration=RuleMigrationV2(schema_service=AmazonSchemaService(db)))
    offline = promo._offline_summary(db, cat, acceptance_data=None)
    svc = ProductListingService(db=db); svc.listing_payload_engine_mode = "v2"
    plan = ProductListingAPIPlanBuilder(svc).build_v2_payload_plan_for_sku(cat, golden)
    prev = ValidationPreviewV2(db=db).preview(plan)
    passed = 1 if prev.status == "validation_preview_passed" else 0
    acceptance = {{"categories": {{cat: {{"offline": offline, "preview": {{"sku_count": 1, "validation_preview_passed": passed}}}}}}}}
    path = Path(f"/app/docs/test-reports/{STAMP}-{{cat.lower()}}-v2-onboard-promote-e2e.json")
    path.write_text(json.dumps(acceptance, indent=2))
    rep = promo.promote(db, cat, write=True, reviewer="{REVIEWER}", require_preview=True, min_preview_passed=1, acceptance_data=acceptance)
    if rep.status not in {{"promoted", "already_live_eligible"}}:
        raise SystemExit(f"promote failed for {{cat}}: {{rep.status}}")
    print(cat, rep.status)
PY
done
"""
    subprocess.run(["docker", "exec", CONTAINER, "bash", "-lc", script], check=True)


def docker_pull_rules_back() -> None:
    for category in CATEGORIES:
        for sub in ("", "v2_onboarded/"):
            dest = RULES_ROOT / sub / f"{category.lower()}.yaml"
            src = (
                f"{CONTAINER}:/app/config/amz_listing_data_mapping/api_attribute_rules/"
                f"{category.lower()}.yaml"
            )
            subprocess.run(["docker", "cp", src, str(dest)], check=True)


def main() -> int:
    prepare_drafts()
    pre = host_precheck()
    stage_to_canonical()
    docker_cp_rules()
    docker_promote_all()
    docker_pull_rules_back()
    out = REPORT_DIR / f"{STAMP}-v2-onboard-live-promote-complete.json"
    out.write_text(json.dumps(pre, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done. {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
