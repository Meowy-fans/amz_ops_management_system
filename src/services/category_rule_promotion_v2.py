"""Go-live promotion gate for category attribute rules (S10)."""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.repositories.pending_rule_review_repository import PendingRuleReviewRepository
from src.repositories.product_listing_repository import ProductListingRepository
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
from src.services.product_listing_api_plan_builder import ProductListingAPIPlanBuilder
from src.services.product_listing_service import ProductListingService
from src.services.review_adapter_v2 import ReviewAdapterV2
from src.services.rule_migration_v2 import RuleMigrationV2
from src.services.rule_review_service_v2 import RuleReviewServiceV2
from src.services.validation_preview_v2 import ValidationPreviewV2


PROMOTED_DECISION = "promoted"
PROMOTED_PATH_KEY = "(root)"
PROMOTED_ISSUE_TYPE = "promoted"


@dataclass
class PromotionCheck:
    name: str
    passed: bool
    detail: str
    required: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "required": self.required,
        }


@dataclass
class PromotionReport:
    product_type: str
    status: str
    checks: List[PromotionCheck] = field(default_factory=list)
    written: bool = False
    yaml_path: Optional[str] = None
    backup_path: Optional[str] = None
    already_live_eligible: bool = False

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks if check.required)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "status": self.status,
            "passed": self.passed,
            "written": self.written,
            "yaml_path": self.yaml_path,
            "backup_path": self.backup_path,
            "already_live_eligible": self.already_live_eligible,
            "checks": [check.as_dict() for check in self.checks],
        }


class CategoryRulePromotionV2:
    """Evaluate promotion checklist and optionally set mode=live_eligible."""

    def __init__(
        self,
        rule_loader: AttributeRuleLoader | None = None,
        review_service: RuleReviewServiceV2 | None = None,
        migration: RuleMigrationV2 | None = None,
    ):
        self.rule_loader = rule_loader or AttributeRuleLoader()
        self.review_service = review_service or RuleReviewServiceV2(
            rule_loader=self.rule_loader
        )
        self.migration = migration or RuleMigrationV2(rule_loader=self.rule_loader)

    def evaluate(
        self,
        db: Session,
        product_type: str,
        *,
        require_preview: bool = False,
        min_preview_passed: int = 1,
        acceptance_data: Optional[Dict[str, Any]] = None,
    ) -> PromotionReport:
        normalized = str(product_type or "").strip().upper()
        rules = self.rule_loader.load(normalized)
        mode = str(rules.get("mode") or AttributeRuleLoader.DEFAULT_MODE)
        already_live = mode == AttributeRuleLoader.LIVE_ELIGIBLE_MODE

        checks: List[PromotionCheck] = []
        if already_live:
            checks.append(
                PromotionCheck(
                    name="already_live_eligible",
                    passed=True,
                    detail="Category rules are already mode=live_eligible",
                    required=False,
                )
            )
            checks.append(
                PromotionCheck(
                    name="mode_is_dry_run",
                    passed=True,
                    detail=f"Skipped; already mode={mode}",
                    required=False,
                )
            )
        else:
            checks.append(
                PromotionCheck(
                    name="mode_is_dry_run",
                    passed=mode == AttributeRuleLoader.DEFAULT_MODE,
                    detail=f"Current mode={mode}",
                )
            )

        review = self.review_service.review_category(normalized, db=db)
        blocking = review.blocking_item_count
        checks.append(
            PromotionCheck(
                name="review_blocking_clear",
                passed=blocking == 0,
                detail=f"blocking_items={blocking}",
            )
        )

        if already_live:
            checks.extend(
                [
                    PromotionCheck(
                        name="s7_offline_zero_missing",
                        passed=True,
                        detail="skipped (already live_eligible)",
                        required=False,
                    ),
                    PromotionCheck(
                        name="s7_preview_min_passed",
                        passed=True,
                        detail="skipped (already live_eligible)",
                        required=False,
                    ),
                    PromotionCheck(
                        name="golden_regression",
                        passed=True,
                        detail="skipped (already live_eligible)",
                        required=False,
                    ),
                ]
            )
            return PromotionReport(
                product_type=normalized,
                status="already_live_eligible",
                checks=checks,
                already_live_eligible=True,
            )

        offline_summary = self._offline_summary(
            db,
            normalized,
            acceptance_data=acceptance_data,
        )
        sku_count = int(offline_summary.get("sku_count") or 0)
        zero_missing = int(offline_summary.get("zero_missing") or 0)
        checks.append(
            PromotionCheck(
                name="s7_offline_zero_missing",
                passed=sku_count > 0 and zero_missing == sku_count,
                detail=f"zero_missing={zero_missing}/{sku_count}",
            )
        )

        preview_summary: Dict[str, Any] = {"validation_preview_passed": 0}
        if require_preview:
            preview_summary = self._preview_summary(
                db,
                normalized,
                acceptance_data=acceptance_data,
            )
        preview_passed = int(preview_summary.get("validation_preview_passed") or 0)
        if require_preview:
            checks.append(
                PromotionCheck(
                    name="s7_preview_min_passed",
                    passed=preview_passed >= int(min_preview_passed),
                    detail=(
                        f"validation_preview_passed={preview_passed} "
                        f"required>={min_preview_passed}"
                    ),
                )
            )
        else:
            checks.append(
                PromotionCheck(
                    name="s7_preview_min_passed",
                    passed=True,
                    detail="skipped (--require-preview not set)",
                    required=False,
                )
            )

        golden_check = self._golden_check(db, normalized)
        checks.append(golden_check)

        status = "go" if all(c.passed for c in checks if c.required) else "no_go"
        if already_live and status == "go":
            status = "already_live_eligible"
        return PromotionReport(
            product_type=normalized,
            status=status,
            checks=checks,
            already_live_eligible=already_live,
        )

    def promote(
        self,
        db: Session,
        product_type: str,
        *,
        write: bool = False,
        reviewer: Optional[str] = None,
        require_preview: bool = False,
        min_preview_passed: int = 1,
        acceptance_data: Optional[Dict[str, Any]] = None,
    ) -> PromotionReport:
        report = self.evaluate(
            db,
            product_type,
            require_preview=require_preview,
            min_preview_passed=min_preview_passed,
            acceptance_data=acceptance_data,
        )
        if not report.passed:
            return report

        normalized = report.product_type
        if report.already_live_eligible:
            return report

        if not write:
            report.status = "go"
            return report

        yaml_path, backup_path = self._write_live_eligible(normalized)
        report.written = True
        report.yaml_path = str(yaml_path)
        report.backup_path = str(backup_path) if backup_path else None
        report.status = "promoted"

        if reviewer:
            PendingRuleReviewRepository(db).upsert_decision(
                category=normalized,
                path_key=PROMOTED_PATH_KEY,
                issue_type=PROMOTED_ISSUE_TYPE,
                decision=PROMOTED_DECISION,
                reviewer=reviewer,
                detail=f"Promoted to live_eligible via promote-category-rules-v2",
                patch_summary={
                    "yaml_path": str(yaml_path),
                    "backup_path": str(backup_path) if backup_path else None,
                },
            )
        return report

    def _offline_summary(
        self,
        db: Session,
        product_type: str,
        *,
        acceptance_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        cached = self._acceptance_section(acceptance_data, product_type, "offline")
        if cached is not None:
            return cached
        skus = self._pool_skus(db, product_type)
        if not skus:
            return {"sku_count": 0, "zero_missing": 0}
        engine = ListingPayloadEngineV2(db=db)
        review = ReviewAdapterV2(db=db)
        rules = self.rule_loader.load(product_type)
        zero_missing = 0
        for sku in skus:
            overrides = review.build_overrides_from_decisions(category=product_type, sku=sku)
            plan = engine.build_read_only_plan(
                product_type=product_type,
                sku=sku,
                rules=rules,
                overrides=overrides or None,
            )
            if not plan.missing_required_paths:
                zero_missing += 1
        return {"sku_count": len(skus), "zero_missing": zero_missing}

    def _preview_summary(
        self,
        db: Session,
        product_type: str,
        *,
        acceptance_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        cached = self._acceptance_section(acceptance_data, product_type, "preview")
        if cached is not None:
            return cached
        skus = self._pool_skus(db, product_type)
        if not skus:
            return {"sku_count": 0, "validation_preview_passed": 0}
        service = ProductListingService(db=db)
        service.listing_payload_engine_mode = "v2"
        plan_builder = ProductListingAPIPlanBuilder(service)
        preview = ValidationPreviewV2(db=db)
        passed = 0
        for sku in skus:
            plan = plan_builder.build_v2_payload_plan_for_sku(product_type, sku)
            result = preview.preview(plan)
            if result.status == "validation_preview_passed":
                passed += 1
        return {"sku_count": len(skus), "validation_preview_passed": passed}

    def _golden_check(self, db: Session, product_type: str) -> PromotionCheck:
        cases = [
            case
            for case in RuleMigrationV2.DEFAULT_GOLDEN_CASES
            if case.product_type == product_type
        ]
        if not cases:
            return PromotionCheck(
                name="golden_regression",
                passed=True,
                detail="skipped (category not in golden set)",
                required=False,
            )
        report = self.migration.evaluate_golden_regression(db, cases=cases)
        failed = [case for case in report.cases if not case.passed]
        detail = f"passed={report.passed}/{report.total}"
        if failed:
            detail += f"; failed={failed[0].product_type}/{failed[0].sku}"
        return PromotionCheck(
            name="golden_regression",
            passed=report.status == "go",
            detail=detail,
        )

    @staticmethod
    def _acceptance_section(
        acceptance_data: Optional[Dict[str, Any]],
        product_type: str,
        section: str,
    ) -> Optional[Dict[str, Any]]:
        if not acceptance_data:
            return None
        category = (acceptance_data.get("categories") or {}).get(product_type) or {}
        value = category.get(section)
        return value if isinstance(value, dict) else None

    @staticmethod
    def _pool_skus(db: Session, product_type: str) -> List[str]:
        repo = ProductListingRepository(db)
        all_skus = repo.get_pending_listing_skus()
        mapping = dict(repo.get_sku_to_category_mapping(all_skus))
        return [sku for sku in all_skus if mapping.get(sku) == product_type]

    @staticmethod
    def load_acceptance_file(path: str | Path) -> Dict[str, Any]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("acceptance file must contain a JSON object")
        return data

    def _write_live_eligible(self, product_type: str) -> tuple[Path, Optional[Path]]:
        import shutil

        from src.services.rule_yaml_write_guard import assert_rule_yaml_write_allowed, write_rule_yaml

        rules = copy.deepcopy(self.rule_loader.load(product_type))
        rules["mode"] = AttributeRuleLoader.LIVE_ELIGIBLE_MODE

        config_dir = Path(self.rule_loader.config_dir)
        target_path = config_dir / f"{product_type.lower()}.yaml"
        backup_path: Optional[Path] = None
        if target_path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = target_path.with_name(f"{target_path.stem}.yaml.bak.{stamp}")
            assert_rule_yaml_write_allowed(backup_path)
            shutil.copy2(target_path, backup_path)

        write_rule_yaml(
            target_path,
            rules,
            product_type=product_type,
            written_by="promote_category_rules_v2",
        )
        return target_path, backup_path
