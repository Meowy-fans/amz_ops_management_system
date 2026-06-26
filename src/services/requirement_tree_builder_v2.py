"""Build read-only RequirementTree objects from Amazon Product Type schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from src.services.amazon_schema_service import AmazonSchemaService
from src.services.requirement_models_v2 import ConditionTrace, RequirementNode, RequirementTree
from src.services.schema_condition_evaluator_v2 import SchemaConditionEvaluatorV2


@dataclass
class ConditionTraceReport:
    """Aggregated condition trace output for one tree build."""

    traces: List[ConditionTrace] = field(default_factory=list)
    non_applicable_required_paths: List[str] = field(default_factory=list)
    unknown_required_paths: List[str] = field(default_factory=list)


class RequirementTreeBuilderV2:
    """Builds applicable requirement trees without changing listing behavior."""

    GENERIC_CHILDREN = {"language_tag", "marketplace_id"}

    def __init__(
        self,
        schema_service: Any,
        condition_evaluator: SchemaConditionEvaluatorV2 | None = None,
        marketplace_id: str = "ATVPDKIKX0DER",
    ):
        self.schema_service = schema_service
        self.condition_evaluator = condition_evaluator or SchemaConditionEvaluatorV2()
        self.marketplace_id = marketplace_id

    def build(
        self,
        product_type: str,
        attributes: Dict[str, Any] | None = None,
        learned_required_paths: List[str] | None = None,
    ) -> RequirementTree:
        normalized = str(product_type or "").strip().upper()
        schema_data = self.schema_service.get_or_fetch_schema(normalized)
        schema = schema_data.get("schema_json", {}) or {}
        properties = AmazonSchemaService._merged_properties(schema)
        required = self._applicable_required(schema_data, schema, attributes or {}, properties)
        self._inject_learned_required(required, learned_required_paths, properties)
        required_paths: List[str] = []
        root = RequirementNode(
            path_key=normalized,
            schema_path="$",
            name=normalized,
            shape="root",
            required=True,
            required_children=list(required),
            condition_state="unconditional",
        )
        for name in required:
            node = self._node_for_property(
                name=name,
                prop_schema=properties.get(name) or {},
                path_key=name,
                schema_path=f"$.properties.{name}",
                required=True,
            )
            root.children.append(node)
            self._collect_required_paths(node, required_paths)
        trace_report = self._condition_trace_report(
            schema,
            attributes or {},
            set(properties),
        )
        return RequirementTree(
            product_type=normalized,
            root=root,
            required_paths=required_paths,
            condition_traces=trace_report.traces,
            non_applicable_required_paths=trace_report.non_applicable_required_paths,
            unknown_required_paths=trace_report.unknown_required_paths,
            iteration_count=1,
            non_converged=False,
        )

    def _inject_learned_required(
        self,
        required: List[str],
        learned_required_paths: List[str] | None,
        properties: Dict[str, Any],
    ) -> None:
        if not learned_required_paths:
            return
        for path_key in learned_required_paths:
            name = str(path_key or "").split(".")[0].split("{")[0]
            if name in properties and name not in required:
                self._append_unique(required, name)

    def _applicable_required(
        self,
        schema_data: Dict[str, Any],
        schema: Dict[str, Any],
        attributes: Dict[str, Any],
        properties: Dict[str, Any],
    ) -> List[str]:
        names: List[str] = []
        self._extend_unique(names, schema_data.get("required_properties") or [])
        self._collect_direct_required(schema, set(properties), names)
        self._collect_conditional_required(schema, attributes, set(properties), names, "$")
        return [name for name in names if name in properties]

    def _collect_direct_required(
        self,
        schema: Dict[str, Any],
        property_names: Set[str],
        names: List[str],
    ) -> None:
        for name in schema.get("required") or []:
            if name in property_names:
                self._append_unique(names, name)
        for idx, part in enumerate(schema.get("allOf") or []):
            if not isinstance(part, dict):
                continue
            for name in part.get("required") or []:
                if name in property_names:
                    self._append_unique(names, name)

    def _collect_conditional_required(
        self,
        schema: Dict[str, Any],
        attributes: Dict[str, Any],
        property_names: Set[str],
        names: List[str],
        schema_path: str,
    ) -> None:
        if not isinstance(schema, dict):
            return
        if "if" in schema:
            result = self.condition_evaluator.evaluate(
                schema.get("if") or {},
                attributes,
                f"{schema_path}.if",
            )
            branch_key = "then" if result.result == "true" else "else"
            if branch_key in schema and result.result in {"true", "false"}:
                block = schema.get(branch_key) or {}
                for name in block.get("required") or []:
                    if name in property_names:
                        self._append_unique(names, name)
                self._collect_conditional_required(
                    block,
                    attributes,
                    property_names,
                    names,
                    f"{schema_path}.{branch_key}",
                )
            return
        for idx, part in enumerate(schema.get("allOf") or []):
            self._collect_conditional_required(
                part or {},
                attributes,
                property_names,
                names,
                f"{schema_path}.allOf[{idx}]",
            )

    def _condition_trace_report(
        self,
        schema: Dict[str, Any],
        attributes: Dict[str, Any],
        property_names: Set[str],
    ) -> ConditionTraceReport:
        report = ConditionTraceReport()
        self._collect_condition_traces(schema, attributes, property_names, report, "$")
        return report

    def _collect_condition_traces(
        self,
        schema: Dict[str, Any],
        attributes: Dict[str, Any],
        property_names: Set[str],
        report: ConditionTraceReport,
        schema_path: str,
    ) -> None:
        if not isinstance(schema, dict):
            return
        if "if" in schema:
            result = self.condition_evaluator.evaluate(
                schema.get("if") or {},
                attributes,
                f"{schema_path}.if",
            )
            then_required = self._known_required((schema.get("then") or {}), property_names)
            else_required = self._known_required((schema.get("else") or {}), property_names)
            introduced: List[str] = []
            non_applicable: List[str] = []
            unknown: List[str] = []
            if result.result == "true":
                introduced = then_required
                non_applicable = else_required
            elif result.result == "false":
                introduced = else_required
                non_applicable = then_required
            else:
                unknown = then_required + [
                    path for path in else_required if path not in then_required
                ]
            self._extend_unique(report.non_applicable_required_paths, non_applicable)
            self._extend_unique(report.unknown_required_paths, unknown)
            report.traces.append(
                ConditionTrace(
                    schema_path=schema_path,
                    operator="if",
                    result=result.result,
                    reason="condition evaluated against candidate payload",
                    dependent_paths=result.dependent_paths,
                    introduced_required_paths=introduced,
                    non_applicable_required_paths=non_applicable,
                    unknown_required_paths=unknown,
                )
            )
            report.traces.extend(result.traces)
        for idx, part in enumerate(schema.get("allOf") or []):
            self._collect_condition_traces(
                part or {},
                attributes,
                property_names,
                report,
                f"{schema_path}.allOf[{idx}]",
            )

    def _known_required(
        self,
        schema: Dict[str, Any],
        property_names: Set[str],
    ) -> List[str]:
        return [
            str(name)
            for name in (schema.get("required") or [])
            if str(name) in property_names
        ]

    def _node_for_property(
        self,
        name: str,
        prop_schema: Dict[str, Any],
        path_key: str,
        schema_path: str,
        required: bool,
    ) -> RequirementNode:
        shape = self._shape(prop_schema)
        required_children = self._required_children(prop_schema)
        node = RequirementNode(
            path_key=path_key,
            schema_path=schema_path,
            name=name,
            shape=shape,
            required=required,
            required_children=required_children,
            enum_values=self._enum_values(prop_schema),
            unit_values=self._unit_values(prop_schema),
            selectors=[str(item) for item in (prop_schema.get("selectors") or [])],
            auto_fields=self._auto_fields(prop_schema),
        )
        child_props = self._child_properties(prop_schema)
        for child_name in required_children:
            child_schema = child_props.get(child_name) or {}
            child_path = f"{path_key}.{child_name}"
            node.children.append(
                self._node_for_property(
                    name=child_name,
                    prop_schema=child_schema,
                    path_key=child_path,
                    schema_path=f"{schema_path}.items.properties.{child_name}",
                    required=True,
                )
            )
        return node

    def _shape(self, schema: Dict[str, Any]) -> str:
        if schema.get("selectors"):
            return "array_object"
        props = self._child_properties(schema)
        if "unit" in props and "value" in props:
            return "measure"
        value_schema = props.get("value") or {}
        if value_schema:
            return "list_value"
        if props:
            return "object"
        if schema.get("type") == "object":
            return "nested_object"
        return "scalar"

    def _required_children(self, schema: Dict[str, Any]) -> List[str]:
        items = schema.get("items") or {}
        required = items.get("required") or schema.get("required") or []
        return [
            str(name)
            for name in required
            if str(name) not in self.GENERIC_CHILDREN
        ]

    @staticmethod
    def _child_properties(schema: Dict[str, Any]) -> Dict[str, Any]:
        items = schema.get("items") or {}
        return dict((items.get("properties") or schema.get("properties") or {}))

    def _enum_values(self, schema: Dict[str, Any]) -> List[str]:
        direct = schema.get("enum")
        if isinstance(direct, list):
            return [str(item) for item in direct]
        value_schema = self._child_properties(schema).get("value") or {}
        enum = value_schema.get("enum")
        if isinstance(enum, list):
            return [str(item) for item in enum]
        return []

    def _unit_values(self, schema: Dict[str, Any]) -> List[str]:
        unit_schema = self._child_properties(schema).get("unit") or {}
        enum = unit_schema.get("enum")
        if isinstance(enum, list):
            return [str(item) for item in enum]
        return []

    def _auto_fields(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}
        props = self._child_properties(schema)
        if "marketplace_id" in props:
            fields["marketplace_id"] = self.marketplace_id
        if "language_tag" in props:
            fields["language_tag"] = "en_US"
        return fields

    def _collect_required_paths(self, node: RequirementNode, paths: List[str]) -> None:
        if node.required:
            self._append_unique(paths, node.path_key)
        for child in node.children:
            self._collect_required_paths(child, paths)

    @staticmethod
    def _append_unique(items: List[str], value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)

    @classmethod
    def _extend_unique(cls, items: List[str], values: List[Any]) -> None:
        for value in values:
            cls._append_unique(items, value)
