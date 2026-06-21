"""Load API-native attribute resolution rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class AttributeRuleLoader:
    """Loads product-type attribute rules from YAML config."""

    DEFAULT_MODE = "dry_run"
    LIVE_ELIGIBLE_MODE = "live_eligible"

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        preset_dir: Optional[Path] = None,
        config_by_type: Optional[Dict[str, Dict[str, Any]]] = None,
        preset_by_name: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        if config_dir is None:
            config_dir = (
                Path(__file__).resolve().parents[2]
                / "config"
                / "amz_listing_data_mapping"
                / "api_attribute_rules"
            )
        self.config_dir = Path(config_dir)
        if preset_dir is None:
            preset_dir = self.config_dir.parent / "api_attribute_presets"
        self.preset_dir = Path(preset_dir)
        self.config_by_type = {
            key.upper(): value for key, value in (config_by_type or {}).items()
        }
        self.preset_by_name = {
            str(key): value for key, value in (preset_by_name or {}).items()
        }

    def load(self, product_type: str) -> Dict[str, Any]:
        """Return attribute rules for a product type, or an empty rule set."""
        normalized = str(product_type or "").upper()
        if normalized in self.config_by_type:
            return self._with_defaults(
                normalized,
                self._apply_presets(self.config_by_type[normalized]),
            )
        path = self.config_dir / f"{normalized.lower()}.yaml"
        if not path.exists():
            return self._with_defaults(normalized, {})
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return self._with_defaults(normalized, self._apply_presets(data))

    def mode(self, product_type: str) -> str:
        """Return the safety mode for one product type's rule set."""
        return str(self.load(product_type).get("mode") or self.DEFAULT_MODE).strip()

    def is_live_eligible(self, product_type: str) -> bool:
        """Return True only when the product type rules explicitly allow LIVE."""
        return self.mode(product_type) == self.LIVE_ELIGIBLE_MODE

    @classmethod
    def _with_defaults(
        cls,
        product_type: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        rules = dict(data or {})
        rules.setdefault("product_type", product_type)
        rules.setdefault("mode", cls.DEFAULT_MODE)
        rules.setdefault("attributes", {})
        return rules

    def _apply_presets(self, data: Dict[str, Any]) -> Dict[str, Any]:
        presets = [
            str(name)
            for name in (data or {}).get("presets") or []
            if str(name or "").strip()
        ]
        if not presets:
            return dict(data or {})

        merged: Dict[str, Any] = {"attributes": {}}
        for name in presets:
            preset = self._load_preset(name)
            merged = self._merge_rule_sets(merged, preset)
        merged = self._merge_rule_sets(merged, data or {})
        merged["presets"] = presets
        return merged

    def _load_preset(self, name: str) -> Dict[str, Any]:
        if name in self.preset_by_name:
            return dict(self.preset_by_name[name] or {})
        path = self.preset_dir / f"{name}.yaml"
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @staticmethod
    def _merge_rule_sets(
        base: Dict[str, Any],
        override: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(base or {})
        override = dict(override or {})
        base_attrs = dict(merged.get("attributes") or {})
        override_attrs = dict(override.get("attributes") or {})
        for key, value in override.items():
            if key == "attributes":
                continue
            merged[key] = value
        base_attrs.update(override_attrs)
        merged["attributes"] = base_attrs
        return merged
