"""Tests for category rule promotion gate (S10)."""

from pathlib import Path
from types import SimpleNamespace

import yaml

from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.category_rule_promotion_v2 import CategoryRulePromotionV2
from src.services.rule_migration_v2 import GoldenRegressionReport, GoldenRegressionCaseResult
from src.services.rule_review_service_v2 import RuleReviewItem, RuleReviewReport


class FakeReviewService:
    def review_category(self, product_type, db=None):
        return RuleReviewReport(
            product_type=product_type,
            leaf_count=1,
            placeholder_leaf_count=0,
            items=[],
        )


class BlockingReviewService:
    def review_category(self, product_type, db=None):
        return RuleReviewReport(
            product_type=product_type,
            leaf_count=1,
            placeholder_leaf_count=1,
            items=[
                RuleReviewItem(
                    product_type=product_type,
                    path_key="frame.material.value",
                    issue_type="todo_placeholder",
                    detail="TODO",
                )
            ],
        )


class FakeMigration:
    def evaluate_golden_regression(self, db, cases=None):
        return GoldenRegressionReport(status="go", passed=1, failed=0, total=1)


class FailingMigration:
    def evaluate_golden_regression(self, db, cases=None):
        return GoldenRegressionReport(
            status="no_go",
            passed=0,
            failed=1,
            total=1,
            cases=[
                GoldenRegressionCaseResult(
                    product_type="CABINET",
                    sku="SKU1",
                    passed=False,
                    baseline_attribute_count=10,
                    migrated_attribute_count=9,
                    differences=["missing brand"],
                )
            ],
        )


def test_evaluate_passes_with_acceptance_file_and_dry_run_mode(tmp_path):
    loader = AttributeRuleLoader(
        config_dir=tmp_path,
        config_by_type={
            "TABLE": {
                "product_type": "TABLE",
                "mode": "dry_run",
                "attributes": {"item_name": {"sources": [{"path": "content.title"}]}},
            }
        },
    )
    service = CategoryRulePromotionV2(
        rule_loader=loader,
        review_service=FakeReviewService(),
        migration=FakeMigration(),
    )
    acceptance = {
        "categories": {
            "TABLE": {
                "offline": {"sku_count": 4, "zero_missing": 4},
                "preview": {"validation_preview_passed": 3},
            }
        }
    }

    report = service.evaluate(
        db=SimpleNamespace(),
        product_type="TABLE",
        require_preview=True,
        min_preview_passed=1,
        acceptance_data=acceptance,
    )

    assert report.passed is True
    assert report.status == "go"
    assert any(check.name == "s7_offline_zero_missing" and check.passed for check in report.checks)


def test_evaluate_fails_when_blocking_review_items_present():
    loader = AttributeRuleLoader(
        config_by_type={
            "CHAIR": {
                "product_type": "CHAIR",
                "mode": "dry_run",
                "attributes": {},
            }
        }
    )
    service = CategoryRulePromotionV2(
        rule_loader=loader,
        review_service=BlockingReviewService(),
        migration=FakeMigration(),
    )
    acceptance = {
        "categories": {
            "CHAIR": {
                "offline": {"sku_count": 2, "zero_missing": 2},
                "preview": {"validation_preview_passed": 0},
            }
        }
    }

    report = service.evaluate(
        db=SimpleNamespace(),
        product_type="CHAIR",
        acceptance_data=acceptance,
    )

    assert report.passed is False
    assert report.status == "no_go"


def test_evaluate_already_live_eligible_is_idempotent():
    loader = AttributeRuleLoader(
        config_by_type={
            "CABINET": {
                "product_type": "CABINET",
                "mode": "live_eligible",
                "attributes": {},
            }
        }
    )
    service = CategoryRulePromotionV2(
        rule_loader=loader,
        review_service=FakeReviewService(),
        migration=FakeMigration(),
    )

    report = service.evaluate(db=SimpleNamespace(), product_type="CABINET")

    assert report.passed is True
    assert report.status == "already_live_eligible"
    assert report.already_live_eligible is True


def test_promote_writes_backup_and_live_eligible_mode(tmp_path):
    yaml_path = tmp_path / "table.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "product_type": "TABLE",
                "mode": "dry_run",
                "attributes": {"item_name": {"sources": [{"path": "content.title"}]}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    loader = AttributeRuleLoader(config_dir=tmp_path)
    service = CategoryRulePromotionV2(
        rule_loader=loader,
        review_service=FakeReviewService(),
        migration=FakeMigration(),
    )
    acceptance = {
        "categories": {
            "TABLE": {
                "offline": {"sku_count": 4, "zero_missing": 4},
            }
        }
    }

    report = service.promote(
        db=SimpleNamespace(),
        product_type="TABLE",
        write=True,
        acceptance_data=acceptance,
    )

    assert report.written is True
    assert report.status == "promoted"
    updated = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert updated["mode"] == "live_eligible"
    backups = list(tmp_path.glob("table.yaml.bak.*"))
    assert len(backups) == 1


def test_golden_regression_required_for_golden_categories():
    loader = AttributeRuleLoader(
        config_by_type={
            "CABINET": {
                "product_type": "CABINET",
                "mode": "dry_run",
                "attributes": {},
            }
        }
    )
    service = CategoryRulePromotionV2(
        rule_loader=loader,
        review_service=FakeReviewService(),
        migration=FailingMigration(),
    )
    acceptance = {
        "categories": {
            "CABINET": {
                "offline": {"sku_count": 1, "zero_missing": 1},
                "preview": {"validation_preview_passed": 1},
            }
        }
    }

    report = service.evaluate(
        db=SimpleNamespace(),
        product_type="CABINET",
        acceptance_data=acceptance,
    )

    assert report.passed is False
    golden = next(check for check in report.checks if check.name == "golden_regression")
    assert golden.passed is False


def test_promote_fails_closed_without_write_when_checklist_fails(tmp_path):
    loader = AttributeRuleLoader(
        config_dir=tmp_path,
        config_by_type={
            "CHAIR": {
                "product_type": "CHAIR",
                "mode": "dry_run",
                "attributes": {},
            }
        },
    )
    service = CategoryRulePromotionV2(
        rule_loader=loader,
        review_service=BlockingReviewService(),
        migration=FakeMigration(),
    )

    report = service.promote(
        db=SimpleNamespace(),
        product_type="CHAIR",
        write=True,
        acceptance_data={
            "categories": {
                "CHAIR": {
                    "offline": {"sku_count": 1, "zero_missing": 1},
                    "preview": {"validation_preview_passed": 0},
                }
            }
        },
    )

    assert report.passed is False
    assert report.written is False
    assert not (tmp_path / "chair.yaml").exists()
