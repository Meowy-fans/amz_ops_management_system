"""Generate draft API-native attribute rules from cached Amazon schemas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.services.amazon_schema_service import AmazonSchemaService
from src.services.attribute_rule_loader import AttributeRuleLoader


@dataclass
class AttributeRuleGenerationResult:
    """Result of generating one product type rule draft."""

    product_type: str
    path: Path
    written: bool
    existed: bool
    required_count: int
    generated_attribute_count: int
    manual_review_count: int
    warnings: List[str]
    rules: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "path": str(self.path),
            "written": self.written,
            "existed": self.existed,
            "required_count": self.required_count,
            "generated_attribute_count": self.generated_attribute_count,
            "manual_review_count": self.manual_review_count,
            "warnings": self.warnings,
            "mode": self.rules.get("mode"),
        }


class AttributeRuleGenerator:
    """Build conservative YAML rule drafts from Product Type Definitions schema."""

    _SENSITIVE_EXACT = {
        "brand",
        "manufacturer",
        "externally_assigned_product_identifier",
        "supplier_declared_has_product_identifier_exemption",
    }
    _SENSITIVE_MARKERS = (
        "gtin",
        "identifier",
        "certification",
        "compliance",
        "regulation",
        "supplier_declared",
    )
    _DEFAULT_SOURCE_CANDIDATES = {
        "model_name": ["product.attributes.Model Name", "product.attributes.mpn", "product.vendor_sku"],
        "model_number": ["product.attributes.Model Number", "product.attributes.mpn", "product.vendor_sku"],
        "part_number": ["product.attributes.Part Number", "product.attributes.mpn", "product.vendor_sku"],
        "material": ["product.attributes.Main Material", "product.attributes.material"],
        "fabric_type": ["product.attributes.Fabric Type", "product.attributes.Main Material"],
        "color": ["product.attributes.Main Color", "product.attributes.color"],
        "room_type": ["product.attributes.Room Type"],
        "mounting_type": ["product.attributes.Mounting Type"],
        "item_shape": ["product.attributes.Item Shape"],
        "number_of_items": ["product.attributes.Number of Items"],
        "included_components": ["product.attributes.Included Components"],
        "special_feature": ["product.attributes.Special Feature"],
        "is_assembly_required": ["product.attributes.Assembly Required", "product.requires_assembly"],
    }

    def __init__(
        self,
        schema_service: AmazonSchemaService,
        output_dir: Optional[Path] = None,
    ):
        self.schema_service = schema_service
        self.output_dir = Path(output_dir) if output_dir else AttributeRuleLoader().config_dir

    def generate(
        self,
        product_type: str,
        write: bool = True,
        overwrite: bool = False,
    ) -> AttributeRuleGenerationResult:
        """Generate a dry-run YAML draft for one Amazon product type."""
        normalized = str(product_type or "").strip().upper()
        if not normalized:
            raise ValueError("product_type is required")

        target_path = self.output_dir / f"{normalized.lower()}.yaml"
        schema_data = self.schema_service.get_or_fetch_schema(normalized)
        schema = schema_data.get("schema_json", {}) or {}
        required = list(schema_data.get("required_properties") or [])
        properties = AmazonSchemaService._merged_properties(schema)
        attribute_names = self._candidate_attribute_names(properties, required)

        warnings: List[str] = []
        attributes: Dict[str, Any] = {}
        manual_review_count = 0
        for name in attribute_names:
            rule = self._rule_for_attribute(name, properties.get(name) or {}, required)
            attributes[name] = rule
            if rule.get("manual_review"):
                manual_review_count += 1

        rules = {
            "product_type": normalized,
            "version": f"{normalized.lower()}_attribute_rules_draft_v1",
            "mode": AttributeRuleLoader.DEFAULT_MODE,
            "generated_from": "amazon_product_type_schema",
            "attributes": attributes,
        }

        existed = target_path.exists()
        written = False
        if write:
            if existed and not overwrite:
                warnings.append("Rule file already exists; not overwritten")
            else:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                target_path.write_text(
                    yaml.safe_dump(rules, sort_keys=False, allow_unicode=False),
                    encoding="utf-8",
                )
                written = True

        return AttributeRuleGenerationResult(
            product_type=normalized,
            path=target_path,
            written=written,
            existed=existed,
            required_count=len(required),
            generated_attribute_count=len(attributes),
            manual_review_count=manual_review_count,
            warnings=warnings,
            rules=rules,
        )

    def _candidate_attribute_names(
        self,
        properties: Dict[str, Any],
        required: List[str],
    ) -> List[str]:
        names: List[str] = []
        for name in required:
            if name in properties and name not in names:
                names.append(name)
        for name in self._DEFAULT_SOURCE_CANDIDATES:
            if name in properties and name not in names:
                names.append(name)
        return names

    def _rule_for_attribute(
        self,
        name: str,
        prop_schema: Dict[str, Any],
        required: List[str],
    ) -> Dict[str, Any]:
        level = "required" if name in required else "recommended"
        shape = self._shape(prop_schema)
        transform = self._transform(name, prop_schema, shape)
        sources = [
            {"path": path}
            for path in self._DEFAULT_SOURCE_CANDIDATES.get(name, [])
        ]
        manual_review = self._is_sensitive(name) or not sources or shape in {
            "object",
            "nested_object",
        }
        if manual_review:
            sources.append({
                "default": None,
                "confidence": "low",
                "evidence": f"TODO: review source mapping for {name}",
            })
        return {
            "level": level,
            "shape": shape,
            "transform": transform,
            "manual_review": manual_review,
            "sources": sources,
        }

    def _shape(self, prop_schema: Dict[str, Any]) -> str:
        items = prop_schema.get("items") or {}
        item_props = items.get("properties") or {}
        value_schema = item_props.get("value") or {}
        if "unit" in item_props and "value" in item_props:
            return "measure"
        if value_schema:
            return "list_value"
        if item_props:
            return "object"
        if prop_schema.get("type") == "object":
            return "nested_object"
        return "value"

    def _transform(
        self,
        name: str,
        prop_schema: Dict[str, Any],
        shape: str,
    ) -> str:
        if shape in {"object", "nested_object", "measure"}:
            return "passthrough"
        if self._has_enum(prop_schema):
            return "enum"
        if name.startswith("is_") or name.startswith("has_"):
            return "boolean_yes_no"
        if name.startswith("number_of_") or name.endswith("_count"):
            return "integer"
        return "text"

    @staticmethod
    def _has_enum(prop_schema: Dict[str, Any]) -> bool:
        items = prop_schema.get("items") or {}
        value_schema = (items.get("properties") or {}).get("value") or {}
        return bool(value_schema.get("enum"))

    @classmethod
    def _is_sensitive(cls, attribute: str) -> bool:
        name = str(attribute or "").strip().lower()
        if name in cls._SENSITIVE_EXACT:
            return True
        return any(marker in name for marker in cls._SENSITIVE_MARKERS)
