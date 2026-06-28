"""Tests for rule YAML write guard."""

import os
from pathlib import Path

import pytest

from src.services.rule_yaml_write_guard import (
    assert_rule_yaml_write_allowed,
    canonical_rule_config_dir,
    write_rule_yaml,
)


def test_assert_rule_yaml_write_allowed_blocks_pytest_writes_to_canonical_dir():
    canonical = canonical_rule_config_dir()
    target = canonical / "table.yaml"
    with pytest.raises(RuntimeError, match="Refusing to write"):
        assert_rule_yaml_write_allowed(target)


def test_assert_rule_yaml_write_allowed_allows_tmp_path_during_pytest(tmp_path):
    assert_rule_yaml_write_allowed(tmp_path / "table.yaml")


def test_assert_rule_yaml_write_allowed_allows_canonical_with_override(monkeypatch):
    monkeypatch.setenv("AMZ_ALLOW_RULE_YAML_WRITE", "1")
    assert_rule_yaml_write_allowed(canonical_rule_config_dir() / "table.yaml")


def test_write_rule_yaml_works_under_tmp_path(tmp_path):
    path = write_rule_yaml(
        tmp_path / "table.yaml",
        {"attributes": {"number_of_items": {"sources": [{"default": 1}]}}},
        product_type="TABLE",
        written_by="test",
    )
    assert path.exists()
    assert "product_type: TABLE" in path.read_text(encoding="utf-8")
