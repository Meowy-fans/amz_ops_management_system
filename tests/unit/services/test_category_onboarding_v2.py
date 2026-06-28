"""Tests for category onboarding orchestration (S8)."""

import json
from pathlib import Path
from types import SimpleNamespace

from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.category_onboarding_v2 import CategoryOnboardingV2
from src.services.rule_field_mapper_v2 import RuleFieldMappingResult
from src.services.rule_pattern_reuse_v2 import RulePatternReuseResult
from src.services.rule_review_service_v2 import RuleReviewReport
from src.services.rule_skeleton_generator_v2 import RuleSkeletonGenerationResult


class FakeSchemaService:
    def __init__(self, cached=True):
        self.cached = cached

    def get_cached_schema(self, product_type):
        return {"schema_json": {}} if self.cached else None


def test_validate_prerequisites_fails_without_cached_schema(tmp_path):
    service = CategoryOnboardingV2(
        db=SimpleNamespace(),
        schema_service=FakeSchemaService(cached=False),
        rule_loader=AttributeRuleLoader(config_dir=tmp_path),
        state_dir=tmp_path / "state",
        report_dir=tmp_path / "reports",
    )
    try:
        service._validate_prerequisites("BED_FRAME", ["SKU1"])
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "No cached schema" in str(exc)


def test_validate_prerequisites_fails_without_pool_skus(tmp_path):
    service = CategoryOnboardingV2(
        db=SimpleNamespace(),
        schema_service=FakeSchemaService(cached=True),
        rule_loader=AttributeRuleLoader(config_dir=tmp_path),
        state_dir=tmp_path / "state",
        report_dir=tmp_path / "reports",
    )
    try:
        service._validate_prerequisites("BED_FRAME", [])
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "No pending pool SKUs" in str(exc)


def test_onboard_runs_pipeline_and_writes_state(tmp_path, monkeypatch):
    loader = AttributeRuleLoader(config_dir=tmp_path)
    onboarding = CategoryOnboardingV2(
        db=SimpleNamespace(),
        schema_service=FakeSchemaService(cached=True),
        rule_loader=loader,
        state_dir=tmp_path / "state",
        report_dir=tmp_path / "reports",
    )
    monkeypatch.setattr(onboarding, "_pool_skus", lambda product_type, limit: ["SKU1", "SKU2"])

    skeleton_path = tmp_path / "bed_frame.yaml"
    skeleton_path.write_text("product_type: BED_FRAME\nmode: dry_run\nattributes: {}\n", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.category_onboarding_v2.RuleSkeletonGeneratorV2",
        lambda *args, **kwargs: SimpleNamespace(
            generate=lambda **kw: RuleSkeletonGenerationResult(
                product_type="BED_FRAME",
                path=skeleton_path,
                written=True,
                existed=False,
                attribute_count=10,
                leaf_path_count=20,
                placeholder_leaf_count=5,
                rules={"product_type": "BED_FRAME", "mode": "dry_run", "attributes": {}},
            )
        ),
    )
    monkeypatch.setattr(
        loader,
        "load",
        lambda product_type: {
            "product_type": "BED_FRAME",
            "mode": "dry_run",
            "attributes": {"item_name": {"sources": [{"path": "content.title"}]}},
        },
    )
    monkeypatch.setattr(
        "src.services.category_onboarding_v2.RulePatternReuseV2",
        lambda *args, **kwargs: SimpleNamespace(
            reuse_patterns=lambda **kw: RulePatternReuseResult(
                product_type="BED_FRAME",
                reference_product_type="TABLE",
                candidate_leaf_count=5,
                reused_leaf_count=2,
                reused_paths=["frame.material.value"],
                rules=kw["rules"],
            )
        ),
    )
    monkeypatch.setattr(
        "src.services.category_onboarding_v2.RuleFieldMapperV2",
        lambda db: SimpleNamespace(
            map_rules=lambda **kw: RuleFieldMappingResult(
                product_type="BED_FRAME",
                sample_sku_count=2,
                leaf_count=5,
                mapped_leaf_count=3,
                mapped_paths=["frame.material.value"],
                rules=kw["rules"],
            )
        ),
    )
    monkeypatch.setattr(
        "src.services.category_onboarding_v2.RuleReviewServiceV2",
        lambda rule_loader: SimpleNamespace(
            review_category=lambda product_type, db=None: RuleReviewReport(
                product_type=product_type,
                leaf_count=5,
                placeholder_leaf_count=1,
                items=[],
            )
        ),
    )
    monkeypatch.setattr(
        "src.services.category_onboarding_v2.CategoryRulePromotionV2",
        lambda rule_loader: SimpleNamespace(
            _offline_summary=lambda db, product_type, acceptance_data=None: {
                "sku_count": 2,
                "zero_missing": 2,
            }
        ),
    )

    report = onboarding.onboard(
        "BED_FRAME",
        reference_product_type="TABLE",
        run_s7_offline=True,
    )

    assert report.status == "completed"
    assert report.yaml_path
    assert Path(report.state_path).exists()
    assert Path(report.acceptance_report_path).exists()
    state = json.loads(Path(report.state_path).read_text(encoding="utf-8"))
    assert state["offline_zero_missing"] == 2
    assert any(step.step == "reuse_rule_patterns_v2" and step.status == "ok" for step in report.steps)
