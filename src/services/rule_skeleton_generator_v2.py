"""Generate V2-ready YAML rule skeletons from Amazon Product Type schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.services.amazon_schema_service import AmazonSchemaService
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.requirement_models_v2 import RequirementNode
from src.services.requirement_tree_builder_v2 import RequirementTreeBuilderV2


@dataclass
class RuleSkeletonGenerationResult:
    """Result of generating one product-type rule skeleton."""

    product_type: str
    path: Path
    written: bool
    existed: bool
    attribute_count: int
    leaf_path_count: int
    placeholder_leaf_count: int
    warnings: List[str] = field(default_factory=list)
    rules: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "path": str(self.path),
            "written": self.written,
            "existed": self.existed,
            "attribute_count": self.attribute_count,
            "leaf_path_count": self.leaf_path_count,
            "placeholder_leaf_count": self.placeholder_leaf_count,
            "warnings": self.warnings,
            "mode": self.rules.get("mode"),
        }


class RuleSkeletonGeneratorV2:
    """Build tree-aware YAML skeletons using RequirementTreeBuilderV2."""

    UNIVERSAL_PRESET = "amazon_universal_required_v1"
    STRUCTURAL_SHAPES = {
        "object",
        "nested_object",
        "measure",
        "measure_array",
        "array_object",
    }
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

    def __init__(
        self,
        schema_service: AmazonSchemaService,
        output_dir: Optional[Path] = None,
        rule_loader: Optional[AttributeRuleLoader] = None,
    ):
        self.schema_service = schema_service
        self.rule_loader = rule_loader or AttributeRuleLoader()
        self.output_dir = Path(output_dir) if output_dir else self.rule_loader.config_dir

    def generate(
        self,
        product_type: str,
        write: bool = True,
        overwrite: bool = False,
    ) -> RuleSkeletonGenerationResult:
        """Generate a dry-run skeleton YAML for one Amazon product type."""
        normalized = str(product_type or "").strip().upper()
        if not normalized:
            raise ValueError("product_type is required")

        target_path = self.output_dir / f"{normalized.lower()}.yaml"
        schema_data = self.schema_service.get_or_fetch_schema(normalized)
        schema = schema_data.get("schema_json", {}) or {}
        properties = AmazonSchemaService._merged_properties(schema)

        tree = RequirementTreeBuilderV2(self.schema_service).build(
            product_type=normalized,
            attributes={},
        )

        attributes: Dict[str, Any] = {}
        leaf_paths: List[str] = []
        for node in tree.root.children:
            if node.name in self._UNIVERSAL_PRESET_ATTRIBUTES:
                continue
            attributes[node.name] = self._rule_for_node(node, top_level=True)
            self._collect_leaf_paths(node, leaf_paths)

        root_config = self._recommend_root_config(properties)
        rules: Dict[str, Any] = {
            "product_type": normalized,
            "version": f"{normalized.lower()}_attribute_rules_skeleton_v2",
            "mode": AttributeRuleLoader.DEFAULT_MODE,
            "generated_from": "rule_skeleton_generator_v2",
            "presets": [self.UNIVERSAL_PRESET],
            **root_config,
            "attributes": attributes,
        }

        placeholder_leaf_count = sum(
            1
            for path_key in leaf_paths
            if self._path_has_placeholder(attributes, path_key)
        )

        warnings: List[str] = []
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

        return RuleSkeletonGenerationResult(
            product_type=normalized,
            path=target_path,
            written=written,
            existed=existed,
            attribute_count=len(attributes),
            leaf_path_count=len(leaf_paths),
            placeholder_leaf_count=placeholder_leaf_count,
            warnings=warnings,
            rules=rules,
        )

    def _rule_for_node(self, node: RequirementNode, top_level: bool) -> Dict[str, Any]:
        yaml_shape = self._yaml_shape(node.shape)
        rule: Dict[str, Any] = {"shape": yaml_shape}
        if top_level:
            rule["level"] = "required" if node.required else "recommended"
            rule["transform"] = self._default_transform(node)
            rule["manual_review"] = True
        if node.enum_values:
            rule["enum_values"] = list(node.enum_values)
        if node.required_children:
            rule["required_children"] = list(node.required_children)
        if node.unit_values:
            rule["unit_values"] = list(node.unit_values)

        if node.children:
            rule["children"] = {
                child.name: self._rule_for_node(child, top_level=False)
                for child in node.children
            }
            return rule

        rule["transform"] = self._default_transform(node)
        rule["sources"] = [self._placeholder_source(node.path_key)]
        return rule

    def _collect_leaf_paths(self, node: RequirementNode, paths: List[str]) -> None:
        if not node.children:
            paths.append(node.path_key)
            return
        for child in node.children:
            self._collect_leaf_paths(child, paths)

    @classmethod
    def _path_has_placeholder(cls, attributes: Dict[str, Any], path_key: str) -> bool:
        parts = path_key.split(".")
        current: Any = {"attributes": attributes}
        rule: Any = attributes
        for part in parts:
            if not isinstance(rule, dict):
                return False
            if part in rule:
                rule = rule[part]
                continue
            children = rule.get("children") or {}
            if part not in children:
                return False
            rule = children[part]
        sources = rule.get("sources") or [] if isinstance(rule, dict) else []
        for source in sources:
            evidence = str(source.get("evidence") or "")
            if evidence.startswith("TODO:"):
                return True
        return False

    @staticmethod
    def _placeholder_source(path_key: str) -> Dict[str, Any]:
        return {
            "default": None,
            "confidence": "low",
            "evidence": f"TODO: review source mapping for {path_key}",
        }

    @classmethod
    def _yaml_shape(cls, shape: str) -> str:
        if shape == "scalar":
            return "value"
        if shape == "measure_array":
            return "measure"
        return shape

    @classmethod
    def _default_transform(cls, node: RequirementNode) -> str:
        shape = node.shape
        name = node.name
        if shape in cls.STRUCTURAL_SHAPES:
            return "passthrough"
        if node.enum_values:
            return "enum"
        if name.startswith("is_") or name.startswith("has_"):
            return "boolean_yes_no"
        if name.startswith("number_of_") or name.endswith("_count"):
            return "integer"
        if shape == "list_value":
            return "text"
        return "text"

    @staticmethod
    def _recommend_root_config(properties: Dict[str, Any]) -> Dict[str, Any]:
        config: Dict[str, Any] = {"coverage_ignore_required": []}
        if "item_depth_width_height" in properties:
            config["dimension_strategy"] = "item_depth_width_height"
        elif "item_length_width_height" in properties:
            config["dimension_strategy"] = "item_length_width_height"
        elif "item_length_width" in properties:
            config["dimension_strategy"] = "item_length_width"
        return config
