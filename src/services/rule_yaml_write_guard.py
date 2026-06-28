"""Guardrails for writing category attribute rule YAML files."""

from __future__ import annotations

import os
from pathlib import Path

from src.services.attribute_rule_loader import AttributeRuleLoader


def canonical_rule_config_dir() -> Path:
    return Path(AttributeRuleLoader().config_dir).resolve()


def assert_rule_yaml_write_allowed(target_path: Path) -> None:
    """Block accidental writes to production rule YAML during pytest."""
    if os.environ.get("AMZ_ALLOW_RULE_YAML_WRITE") == "1":
        return
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return
    target = Path(target_path).resolve()
    canonical = canonical_rule_config_dir()
    try:
        target.relative_to(canonical)
    except ValueError:
        return
    raise RuntimeError(
        f"Refusing to write {target} during pytest. "
        "Use tmp_path config_dir on the rule loader/service under test."
    )


def write_rule_yaml(
    target_path: Path,
    rules: dict,
    *,
    product_type: str,
    written_by: str,
) -> Path:
    """Write one category rule file with pytest guard."""
    import yaml

    assert_rule_yaml_write_allowed(target_path)
    merged = dict(rules)
    merged.setdefault("product_type", product_type)
    merged["generated_from"] = written_by
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        yaml.safe_dump(merged, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return target_path
