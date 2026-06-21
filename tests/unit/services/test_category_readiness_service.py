"""Unit tests for category readiness checks."""

from pathlib import Path

from src.services.category_readiness_service import CategoryReadinessService
from src.services.attribute_rule_loader import AttributeRuleLoader


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Db:
    def execute(self, query):
        return Result([
            ("SOFA", 1, 19),
            ("CABINET", 2, 7),
            ("UNMAPPED", 29, 66),
        ])


class FakeSchemaService:
    def get_cached_schema(self, product_type):
        schemas = {
            "SOFA": {"required_properties": ["item_name", "fabric_type", "arm_style"]},
            "CABINET": {"required_properties": ["item_name", "fabric_type"]},
        }
        return schemas.get(product_type)


def test_readiness_classifies_live_dry_run_and_unmapped(tmp_path: Path):
    (tmp_path / "cabinet.yaml").write_text("product_type: CABINET\n", encoding="utf-8")
    (tmp_path / "sofa.yaml").write_text("product_type: SOFA\n", encoding="utf-8")
    loader = AttributeRuleLoader(
        config_dir=tmp_path,
        config_by_type={
            "CABINET": {
                "product_type": "CABINET",
                "mode": "live_eligible",
                "attributes": {"fabric_type": {}},
            },
            "SOFA": {
                "product_type": "SOFA",
                "mode": "dry_run",
                "attributes": {"fabric_type": {}, "arm_style": {}},
            },
        },
    )
    service = CategoryReadinessService(
        db=Db(),
        schema_service=FakeSchemaService(),
        rule_loader=loader,
    )

    result = {item.product_type: item for item in service.list_readiness()}

    assert result["CABINET"].status == "ready_live"
    assert result["SOFA"].status == "ready_dry_run"
    assert result["UNMAPPED"].status == "unmapped"
    assert service.pending_counts()[0] == {
        "product_type": "SOFA",
        "pending_count": 19,
        "status": "ready_dry_run",
    }


def test_readiness_flags_schema_only_when_rules_are_missing(tmp_path: Path):
    loader = AttributeRuleLoader(config_dir=tmp_path)
    service = CategoryReadinessService(
        db=Db(),
        schema_service=FakeSchemaService(),
        rule_loader=loader,
    )

    result = {item.product_type: item for item in service.list_readiness()}

    assert result["SOFA"].status == "schema_only"
    assert "rules_missing" in result["SOFA"].warnings
