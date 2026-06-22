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

    UNIVERSAL_PRESET = "amazon_universal_required_v1"
    SAFE_DEFAULT_PRESET = "amazon_required_safe_defaults_v1"
    _UNIVERSAL_PRESET_ATTRIBUTES = {
        "item_name",
        "bullet_point",
        "product_description",
        "brand",
        "manufacturer",
        "target_audience_base",
        "item_type_keyword",
        "item_type_name",
        "country_of_origin",
        "supplier_declared_dg_hz_regulation",
        "externally_assigned_product_identifier",
        "supplier_declared_has_product_identifier_exemption",
    }
    _SAFE_DEFAULT_ATTRIBUTES = {
        "brand",
        "manufacturer",
        "supplier_declared_dg_hz_regulation",
        "supplier_declared_has_product_identifier_exemption",
    }
    _SENSITIVE_EXACT = {
        "externally_assigned_product_identifier",
        "supplier_declared_has_product_identifier_exemption",
    }
    _SENSITIVE_MARKERS = (
        "gtin",
        "identifier",
        "certification",
        "compliance",
        "regulation",
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
        "brand": [
            {
                "default": "Generic",
                "confidence": "medium",
                "evidence": "Fallback brand for unbranded Giga products.",
            }
        ],
        "manufacturer": [
            {
                "default": "Nova Home Essentials",
                "confidence": "medium",
                "evidence": "Existing production default manufacturer for Giga-sourced products.",
            }
        ],
        "country_of_origin": [
            {"path": "product.attributes.place_of_origin"},
            {
                "default": "CN",
                "confidence": "medium",
                "evidence": "Fallback country for Giga products when place_of_origin is missing.",
            },
        ],
        "supplier_declared_dg_hz_regulation": [
            {
                "default": "not_applicable",
                "confidence": "medium",
                "evidence": (
                    "Default for non-hazardous goods; review per category for "
                    "battery or hazmat risk."
                ),
            }
        ],
        "item_name": [{"path": "content.title"}],
        "product_description": [{"path": "content.description"}],
        "bullet_point": [{"path": "content.bullets", "transform": "passthrough"}],
        "target_audience_base": [
            {
                "default": "Homeowners",
                "confidence": "medium",
                "evidence": "Default target audience for home and furniture products.",
            }
        ],
        "item_type_keyword": [{"path": "content.title"}],
        "item_type_name": [{"path": "content.title"}],
    }

    def __init__(
        self,
        schema_service: AmazonSchemaService,
        output_dir: Optional[Path] = None,
        rule_loader: Optional[AttributeRuleLoader] = None,
    ):
        self.schema_service = schema_service
        self.rule_loader = rule_loader or AttributeRuleLoader()
        self.output_dir = Path(output_dir) if output_dir else self.rule_loader.config_dir
        self._safe_default_rules = self._load_safe_default_rules()

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
        required = self._required_properties(normalized, schema_data)
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
            "presets": [self.UNIVERSAL_PRESET],
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

    def _required_properties(
        self,
        product_type: str,
        schema_data: Dict[str, Any],
    ) -> List[str]:
        if hasattr(self.schema_service, "get_coverage_required_properties"):
            try:
                required = self.schema_service.get_coverage_required_properties(product_type)
                if required:
                    return list(required)
            except Exception:
                pass
        return list(schema_data.get("required_properties") or [])

    def _candidate_attribute_names(
        self,
        properties: Dict[str, Any],
        required: List[str],
    ) -> List[str]:
        names: List[str] = []
        for name in required:
            if (
                name in properties
                and name not in names
                and name not in self._UNIVERSAL_PRESET_ATTRIBUTES
            ):
                names.append(name)
        for name in self._DEFAULT_SOURCE_CANDIDATES:
            if (
                name in properties
                and name not in names
                and name not in self._UNIVERSAL_PRESET_ATTRIBUTES
            ):
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
        default_transform = self._transform(name, prop_schema, shape)
        sources: List[Dict[str, Any]] = []
        override_transform = None
        for candidate in self._DEFAULT_SOURCE_CANDIDATES.get(name, []):
            entry: Dict[str, Any] = {}
            if isinstance(candidate, str):
                entry["path"] = candidate
            elif isinstance(candidate, dict):
                if "path" in candidate:
                    entry["path"] = candidate["path"]
                if "default" in candidate:
                    entry["default"] = candidate["default"]
                    entry["confidence"] = candidate.get("confidence", "medium")
                    entry["evidence"] = candidate.get("evidence", "")
                if "llm" in candidate:
                    entry["llm"] = candidate["llm"]
                if "transform" in candidate:
                    override_transform = candidate["transform"]
            if entry:
                sources.append(entry)
        is_sensitive_attr = (
            self._is_sensitive(name) and name not in self._SAFE_DEFAULT_ATTRIBUTES
        )
        is_structural_attr = shape in {"object", "nested_object"}
        eligible_required = (
            level == "required"
            and not is_sensitive_attr
            and not is_structural_attr
        )
        safe_default = self._safe_default_source(name)
        has_initial_sources = bool(sources)
        if eligible_required:
            if not self._has_source_type(sources, "llm"):
                sources.append({"llm": {"hint": self._auto_llm_hint(name)}})
            if safe_default and not self._has_concrete_default(sources):
                sources.append(safe_default)
            elif not safe_default and not self._has_source_type(sources, "default"):
                sources.append({
                    "default": None,
                    "confidence": "low",
                    "evidence": f"TODO: review safe default for {name}",
                })
        manual_review = (
            is_sensitive_attr
            or is_structural_attr
            or not sources
            or (eligible_required and not has_initial_sources and not safe_default)
        )
        if manual_review and not sources:
            sources.append({
                "default": None,
                "confidence": "low",
                "evidence": f"TODO: review source mapping for {name}",
            })
        return {
            "level": level,
            "shape": shape,
            "transform": override_transform or default_transform,
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

    def _load_safe_default_rules(self) -> Dict[str, Dict[str, Any]]:
        preset = self.rule_loader.load_preset(self.SAFE_DEFAULT_PRESET)
        return dict((preset.get("attributes") or {}))

    def _safe_default_source(self, name: str) -> Dict[str, Any]:
        rule = self._safe_default_rules.get(name) or {}
        for source in rule.get("sources") or []:
            if "default" not in source:
                continue
            return {
                "default": source.get("default"),
                "confidence": source.get("confidence", "medium"),
                "evidence": source.get("evidence", ""),
                "safe_default": True,
            }
        return {}

    @staticmethod
    def _auto_llm_hint(name: str) -> str:
        label = str(name or "").replace("_", " ")
        return (
            f"Extract {label} from the product title, description, bullet points, "
            "and supplier characteristics. Return null if the information is not found."
        )

    @staticmethod
    def _has_source_type(sources: List[Dict[str, Any]], source_type: str) -> bool:
        return any(source_type in source for source in sources)

    @staticmethod
    def _has_concrete_default(sources: List[Dict[str, Any]]) -> bool:
        return any("default" in source and source.get("default") is not None for source in sources)
