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
        config_by_type: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        if config_dir is None:
            config_dir = (
                Path(__file__).resolve().parents[2]
                / "config"
                / "amz_listing_data_mapping"
                / "api_attribute_rules"
            )
        self.config_dir = Path(config_dir)
        self.config_by_type = {
            key.upper(): value for key, value in (config_by_type or {}).items()
        }

    def load(self, product_type: str) -> Dict[str, Any]:
        """Return attribute rules for a product type, or an empty rule set."""
        normalized = str(product_type or "").upper()
        if normalized in self.config_by_type:
            return self._with_defaults(normalized, self.config_by_type[normalized])
        path = self.config_dir / f"{normalized.lower()}.yaml"
        if not path.exists():
            return self._with_defaults(normalized, {})
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return self._with_defaults(normalized, data)

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
