"""Merge YAML rule-defined optional children into composed listing attributes."""

from __future__ import annotations

from typing import Any, Dict, List

from infrastructure.amazon.config import AmazonConfig
from src.services.evidence_resolver_v2 import EvidenceResolverV2
from src.services.payload_composer_v2 import PayloadComposerV2
from src.services.requirement_models_v2 import RequirementNode, ResolutionNode


class OptionalRuleChildrenEnricherV2:
    """Render rule children not present in the RequirementTree into payload objects."""

    def enrich(
        self,
        attributes: Dict[str, Any],
        rules: Dict[str, Any],
        requirement_root: RequirementNode,
        draft: Any,
        resolver: EvidenceResolverV2,
        candidate_attributes: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        merged = dict(attributes or {})
        requirement_by_name = {node.name: node for node in requirement_root.children}
        composer = PayloadComposerV2()
        ignored_roots = {
            str(name)
            for name in (rules.get("coverage_ignore_required") or [])
            if str(name or "").strip()
        }

        for attr_name, rule in (rules.get("attributes") or {}).items():
            if attr_name in ignored_roots:
                continue
            child_rules = rule.get("children") or {}
            if not child_rules:
                continue
            requirement = requirement_by_name.get(attr_name)
            payload = merged.get(attr_name)
            if payload in (None, "", []) and requirement is not None:
                bootstrapped = self._bootstrap_parent_payload(requirement)
                if bootstrapped is not None:
                    merged[attr_name] = bootstrapped
                    payload = bootstrapped
            if payload in (None, "", []):
                continue
            required_children = (
                {child.name for child in requirement.children} if requirement else set()
            )
            payload_items = payload if isinstance(payload, list) else [payload]
            for child_name, child_rule in child_rules.items():
                if child_name in required_children:
                    continue
                child_requirement = self._requirement_from_rule(
                    attr_name,
                    child_name,
                    child_rule,
                )
                child_resolution = resolver._resolve_node(
                    child_requirement,
                    draft,
                    child_rule,
                    {},
                    candidate_attributes or {},
                    str(rules.get("version") or ""),
                )
                if (
                    child_requirement.shape == "list_value"
                    and child_resolution.value in (None, "")
                    and child_resolution.children
                ):
                    child_resolution.value = child_resolution.children[0].value
                resolution_index = self._index_resolutions(child_resolution)
                rendered = composer._render_node(
                    child_requirement,
                    child_resolution,
                    resolution_index,
                )
                if rendered in (None, "", []):
                    continue
                # Object-embedded measures are flat dicts unless the YAML rule
                # declares measure_array (e.g. seat.height). Top-level measure
                # arrays are handled by PayloadComposerV2._render_top_level().
                if (
                    str(child_rule.get("shape") or "") == "measure_array"
                    and isinstance(rendered, dict)
                ):
                    rendered = [rendered]
                for item in payload_items:
                    if not isinstance(item, dict):
                        continue
                    if item.get(child_name) not in (None, "", []):
                        continue
                    item[child_name] = rendered
            merged[attr_name] = payload
        return merged

    @classmethod
    def strip_incomplete_ignored_attributes(
        cls,
        attributes: Dict[str, Any],
        ignored_roots: List[str] | None,
    ) -> Dict[str, Any]:
        """Drop ignore-listed attributes when payload would partial-emit (e.g. MSA 99022)."""
        merged = dict(attributes or {})
        for root in ignored_roots or []:
            name = str(root or "").strip()
            if not name or name not in merged:
                continue
            if cls._attribute_payload_incomplete(merged.get(name)):
                del merged[name]
        return merged

    @staticmethod
    def _attribute_payload_incomplete(payload: Any) -> bool:
        if payload in (None, "", []):
            return False
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            if "value" in item and item.get("value") in (None, ""):
                return True
            if set(item.keys()) <= {"marketplace_id"}:
                return True
        return False

    def _requirement_from_rule(
        self,
        attr_name: str,
        child_name: str,
        rule: Dict[str, Any],
    ) -> RequirementNode:
        shape = str(rule.get("shape") or "scalar")
        if shape == "value":
            shape = "scalar"
        if shape == "measure_array":
            shape = "measure"
        path_key = f"{attr_name}.{child_name}"
        node = RequirementNode(
            path_key=path_key,
            schema_path=path_key,
            name=child_name,
            shape=shape,
            required=False,
        )
        child_rules = rule.get("children") or {}
        if shape == "measure":
            for part in ("value", "unit"):
                part_rule = child_rules.get(part) or {}
                part_shape = "scalar"
                node.children.append(
                    RequirementNode(
                        path_key=f"{path_key}.{part}",
                        schema_path=f"{path_key}.{part}",
                        name=part,
                        shape=part_shape,
                        required=part in (rule.get("required_children") or ["value", "unit"]),
                    )
                )
        elif shape == "list_value":
            node.auto_fields = {"language_tag": "en_US"}
            value_rule = child_rules.get("value") or {}
            node.children.append(
                RequirementNode(
                    path_key=f"{path_key}.value",
                    schema_path=f"{path_key}.value",
                    name="value",
                    shape="scalar",
                    required=True,
                )
            )
            if value_rule.get("enum_values"):
                node.children[-1].enum_values = list(value_rule["enum_values"])
        return node

    @staticmethod
    def _bootstrap_parent_payload(requirement: RequirementNode) -> Any | None:
        if requirement.shape == "array_object":
            return [{"marketplace_id": AmazonConfig.MARKETPLACE_ID}]
        if requirement.shape in {"object", "nested_object"}:
            return {}
        return None

    @staticmethod
    def _index_resolutions(root: ResolutionNode) -> Dict[str, ResolutionNode]:
        index: Dict[str, ResolutionNode] = {}

        def visit(node: ResolutionNode) -> None:
            index[node.path_key] = node
            for child in node.children:
                visit(child)

        visit(root)
        return index
