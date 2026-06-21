"""Configuration helpers for Amazon listing quality gate rules."""

import os
from typing import Any, Dict, Optional

import yaml


class QualityGateRuleLoader:
    """Loads issue-derived quality gate rules from YAML."""

    _config: Optional[Dict[str, Any]] = None
    _config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "config",
        "listing_gates",
        "quality_gate.yaml",
    )

    @classmethod
    def load(cls) -> Dict[str, Any]:
        if cls._config is None:
            if not os.path.exists(cls._config_path):
                cls._config = {}
            else:
                with open(cls._config_path, "r", encoding="utf-8") as f:
                    cls._config = yaml.safe_load(f) or {}
        return cls._config


def dimension_range_rule(
    config: Dict[str, Any],
    product_type: str,
    attribute_name: str,
    dimension_name: str,
) -> Dict[str, Any]:
    ranges = config.get("dimension_ranges") or {}
    product_rules = ranges.get(product_type.upper()) or ranges.get(product_type.lower())
    if not isinstance(product_rules, dict):
        return {}
    attr_rules = product_rules.get(attribute_name) or {}
    if not isinstance(attr_rules, dict):
        return {}
    rule = attr_rules.get(dimension_name) or {}
    return rule if isinstance(rule, dict) else {}
