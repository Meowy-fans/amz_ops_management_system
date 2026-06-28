"""Tests for Layer 1 YAML rule review."""

from pathlib import Path

import pytest

from src.services.rule_review_service_v2 import RuleReviewServiceV2


class FakeLoader:
    def __init__(self, rules_by_type=None, config_dir=None):
        self.rules_by_type = rules_by_type or {}
        self.config_dir = config_dir or Path("/tmp/rules")

    def load(self, product_type):
        return self.rules_by_type.get(product_type, self.rules_by_type.get("DEFAULT", {}))


class FakeRepo:
    def __init__(self):
        self.rows = []

    def upsert_decision(self, **kwargs):
        self.rows.append(kwargs)
        return len(self.rows)

    def list_decisions(self, category):
        return [
            row
            for row in self.rows
            if row.get("category") == category
        ]


def test_review_category_finds_placeholder_and_structural_parent_sources():
    loader = FakeLoader(
        {
            "TABLE": {
                "product_type": "TABLE",
                "attributes": {
                    "frame": {
                        "shape": "object",
                        "sources": [
                            {"default": None, "evidence": "TODO: review source mapping for frame"}
                        ],
                        "children": {
                            "material": {
                                "children": {
                                    "value": {
                                        "sources": [
                                            {
                                                "default": None,
                                                "evidence": (
                                                    "TODO: review source mapping for "
                                                    "frame.material.value"
                                                ),
                                            }
                                        ]
                                    }
                                }
                            }
                        },
                    },
                    "number_of_items": {
                        "sources": [
                            {
                                "default": 1,
                                "confidence": "medium",
                                "evidence": "fallback",
                            }
                        ]
                    },
                },
            }
        }
    )
    report = RuleReviewServiceV2(rule_loader=loader).review_category("TABLE")

    issue_types = {item.issue_type for item in report.items}
    assert "todo_placeholder" in issue_types
    assert "structural_parent_sources" in issue_types
    assert "unsafe_default" in issue_types
    assert report.placeholder_leaf_count == 1


def test_review_category_flags_risk_partial_emit_for_ignore_listed_attribute_block():
    loader = FakeLoader(
        {
            "BED_FRAME": {
                "product_type": "BED_FRAME",
                "coverage_ignore_required": ["merchant_suggested_asin"],
                "attributes": {
                    "merchant_suggested_asin": {
                        "shape": "array_object",
                        "children": {
                            "value": {"sources": [{"default": None}]},
                        },
                    }
                },
            }
        }
    )
    report = RuleReviewServiceV2(rule_loader=loader).review_category("BED_FRAME")
    assert any(item.issue_type == "risk_partial_emit" for item in report.items)


def test_review_category_does_not_flag_ignore_only_without_attribute_block():
    loader = FakeLoader(
        {
            "CABINET": {
                "product_type": "CABINET",
                "coverage_ignore_required": ["merchant_suggested_asin"],
                "attributes": {},
            }
        }
    )
    report = RuleReviewServiceV2(rule_loader=loader).review_category("CABINET")
    assert not any(item.issue_type == "risk_partial_emit" for item in report.items)


def test_approve_safe_default_writes_yaml_and_clears_unsafe_default(tmp_path):
    rules = {
        "product_type": "TABLE",
        "attributes": {
            "number_of_items": {
                "sources": [
                    {
                        "default": 1,
                        "confidence": "medium",
                        "evidence": "fallback",
                    }
                ]
            }
        },
    }
    loader = FakeLoader({"TABLE": rules}, config_dir=tmp_path)
    repo = FakeRepo()
    service = RuleReviewServiceV2(rule_loader=loader, review_repo=repo)

    result = service.approve_rule(
        product_type="TABLE",
        path_key="number_of_items",
        decision="safe_default",
        reviewer="operator@test",
        write=True,
    )

    assert result.written is True
    written = (tmp_path / "table.yaml").read_text(encoding="utf-8")
    assert "safe_default: true" in written
    import yaml

    loader.rules_by_type["TABLE"] = yaml.safe_load(written)
    rescanned = service.review_category("TABLE")
    assert not any(item.issue_type == "unsafe_default" for item in rescanned.items)


def test_approve_coverage_ignore_removes_attribute_block(tmp_path):
    rules = {
        "product_type": "BED_FRAME",
        "coverage_ignore_required": ["merchant_shipping_group"],
        "attributes": {
            "merchant_suggested_asin": {
                "shape": "array_object",
                "children": {"value": {"sources": [{"default": None}]}},
            }
        },
    }
    loader = FakeLoader({"BED_FRAME": rules}, config_dir=tmp_path)
    service = RuleReviewServiceV2(rule_loader=loader, review_repo=FakeRepo())

    result = service.approve_rule(
        product_type="BED_FRAME",
        path_key="merchant_suggested_asin",
        decision="coverage_ignore",
        reviewer="operator@test",
        write=True,
    )

    assert result.patch_summary["removed_attribute_block"] is True
    written = (tmp_path / "bed_frame.yaml").read_text(encoding="utf-8")
    assert "merchant_suggested_asin:" not in written
    assert "merchant_suggested_asin" in written


def test_approve_waived_suppresses_issue_without_yaml_change():
    rules = {
        "product_type": "TABLE",
        "attributes": {
            "finish_type": {
                "sources": [
                    {
                        "default": "Matte",
                        "confidence": "medium",
                        "inherited_from": "CHAIR",
                        "evidence": "reuse",
                    }
                ]
            }
        },
    }
    loader = FakeLoader({"TABLE": rules})
    repo = FakeRepo()
    service = RuleReviewServiceV2(rule_loader=loader, review_repo=repo)

    before = service.review_category("TABLE")
    assert any(item.issue_type == "inherited_source" for item in before.items)

    service.approve_rule(
        product_type="TABLE",
        path_key="finish_type",
        decision="waived",
        reviewer="operator@test",
        issue_type="inherited_source",
        write=False,
    )

    after = service.review_category("TABLE")
    assert not any(item.issue_type == "inherited_source" for item in after.items)


def test_approve_requires_default_for_safe_default():
    loader = FakeLoader(
        {
            "TABLE": {
                "attributes": {
                    "finish_type": {
                        "sources": [{"path": "product.attributes.Finish"}]
                    }
                }
            }
        }
    )
    service = RuleReviewServiceV2(rule_loader=loader, review_repo=FakeRepo())
    with pytest.raises(ValueError, match="No default source"):
        service.approve_rule(
            product_type="TABLE",
            path_key="finish_type",
            decision="safe_default",
            reviewer="operator@test",
        )
