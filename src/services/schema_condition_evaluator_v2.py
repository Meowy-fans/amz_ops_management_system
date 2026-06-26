"""Conservative JSON Schema condition evaluator for payload engine V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.services.requirement_models_v2 import ConditionTrace


@dataclass
class ConditionEvaluation:
    """Result of evaluating a schema predicate."""

    result: str
    traces: List[ConditionTrace] = field(default_factory=list)
    dependent_paths: List[str] = field(default_factory=list)

    @property
    def is_true(self) -> bool:
        return self.result == "true"

    @property
    def is_false(self) -> bool:
        return self.result == "false"

    @property
    def is_unknown(self) -> bool:
        return self.result in {"unknown", "unsupported"}


class SchemaConditionEvaluatorV2:
    """Evaluate a supported subset of Amazon Product Type schema conditions."""

    SUPPORTED_SCHEMA_KEYS = {
        "allOf",
        "anyOf",
        "const",
        "contains",
        "else",
        "enum",
        "if",
        "items",
        "not",
        "oneOf",
        "properties",
        "required",
        "then",
        "type",
    }
    ANNOTATION_KEYS = {
        "$comment",
        "$id",
        "$schema",
        "description",
        "examples",
        "title",
    }

    def evaluate(
        self,
        schema: Dict[str, Any],
        payload: Dict[str, Any],
        schema_path: str = "$",
    ) -> ConditionEvaluation:
        if not isinstance(schema, dict):
            return self._result("true", schema_path, "schema", "empty predicate")

        unsupported = self._unsupported_keywords(schema)
        if unsupported:
            return self._result(
                "unsupported",
                schema_path,
                "schema",
                f"unsupported predicate keywords: {', '.join(unsupported)}",
            )

        if "allOf" in schema:
            return self._combine_all(schema.get("allOf") or [], payload, schema_path)
        if "anyOf" in schema:
            return self._combine_any(schema.get("anyOf") or [], payload, schema_path)
        if "oneOf" in schema:
            return self._combine_one(schema.get("oneOf") or [], payload, schema_path)
        if "not" in schema:
            child = self.evaluate(schema.get("not") or {}, payload, f"{schema_path}.not")
            if child.result == "true":
                result = "false"
            elif child.result == "false":
                result = "true"
            else:
                result = child.result
            child.traces.append(
                ConditionTrace(
                    schema_path=schema_path,
                    operator="not",
                    result=result,
                    reason=f"not({child.result})",
                    dependent_paths=child.dependent_paths,
                )
            )
            return ConditionEvaluation(result, child.traces, child.dependent_paths)

        traces: List[ConditionTrace] = []
        dependent_paths: List[str] = []

        for name in schema.get("required") or []:
            text = str(name)
            dependent_paths.append(text)
            if not self._has_value(payload.get(text)):
                return ConditionEvaluation(
                    "false",
                    [
                        ConditionTrace(
                            schema_path=schema_path,
                            operator="required",
                            result="false",
                            reason=f"payload path '{text}' is missing or empty",
                            dependent_paths=[text],
                        )
                    ],
                    dependent_paths,
                )

        for name, predicate in (schema.get("properties") or {}).items():
            if name not in payload:
                continue
            dependent_paths.append(str(name))
            matched = self._matches_value_schema(
                payload.get(name),
                predicate or {},
                f"{schema_path}.properties.{name}",
            )
            traces.extend(matched.traces)
            dependent_paths.extend(matched.dependent_paths)
            if matched.result != "true":
                return ConditionEvaluation(matched.result, traces, dependent_paths)

        if "contains" in schema:
            # Root-level contains only makes sense when payload itself is an array.
            matched = self._matches_contains(
                payload,
                schema.get("contains") or {},
                f"{schema_path}.contains",
            )
            traces.extend(matched.traces)
            dependent_paths.extend(matched.dependent_paths)
            if matched.result != "true":
                return ConditionEvaluation(matched.result, traces, dependent_paths)

        if "enum" in schema or "const" in schema:
            matched = self._matches_scalar_constraint(payload, schema, schema_path)
            traces.extend(matched.traces)
            dependent_paths.extend(matched.dependent_paths)
            if matched.result != "true":
                return ConditionEvaluation(matched.result, traces, dependent_paths)

        traces.append(
            ConditionTrace(
                schema_path=schema_path,
                operator="schema",
                result="true",
                reason="supported predicates matched",
                dependent_paths=sorted(set(dependent_paths)),
            )
        )
        return ConditionEvaluation("true", traces, sorted(set(dependent_paths)))

    def _combine_all(
        self,
        schemas: List[Any],
        payload: Dict[str, Any],
        schema_path: str,
    ) -> ConditionEvaluation:
        traces: List[ConditionTrace] = []
        deps: List[str] = []
        saw_unknown = False
        for idx, part in enumerate(schemas):
            child = self.evaluate(part or {}, payload, f"{schema_path}.allOf[{idx}]")
            traces.extend(child.traces)
            deps.extend(child.dependent_paths)
            if child.result == "false":
                return ConditionEvaluation("false", traces, sorted(set(deps)))
            if child.is_unknown:
                saw_unknown = True
        return ConditionEvaluation("unknown" if saw_unknown else "true", traces, sorted(set(deps)))

    def _combine_any(
        self,
        schemas: List[Any],
        payload: Dict[str, Any],
        schema_path: str,
    ) -> ConditionEvaluation:
        traces: List[ConditionTrace] = []
        deps: List[str] = []
        saw_unknown = False
        for idx, part in enumerate(schemas):
            child = self.evaluate(part or {}, payload, f"{schema_path}.anyOf[{idx}]")
            traces.extend(child.traces)
            deps.extend(child.dependent_paths)
            if child.result == "true":
                return ConditionEvaluation("true", traces, sorted(set(deps)))
            if child.is_unknown:
                saw_unknown = True
        return ConditionEvaluation("unknown" if saw_unknown else "false", traces, sorted(set(deps)))

    def _combine_one(
        self,
        schemas: List[Any],
        payload: Dict[str, Any],
        schema_path: str,
    ) -> ConditionEvaluation:
        traces: List[ConditionTrace] = []
        deps: List[str] = []
        true_count = 0
        saw_unknown = False
        for idx, part in enumerate(schemas):
            child = self.evaluate(part or {}, payload, f"{schema_path}.oneOf[{idx}]")
            traces.extend(child.traces)
            deps.extend(child.dependent_paths)
            if child.result == "true":
                true_count += 1
            elif child.is_unknown:
                saw_unknown = True
        if saw_unknown:
            return ConditionEvaluation("unknown", traces, sorted(set(deps)))
        return ConditionEvaluation("true" if true_count == 1 else "false", traces, sorted(set(deps)))

    def _matches_value_schema(
        self,
        value: Any,
        schema: Dict[str, Any],
        schema_path: str,
    ) -> ConditionEvaluation:
        if not isinstance(schema, dict):
            return self._result("true", schema_path, "schema", "empty value schema")

        unsupported = self._unsupported_keywords(schema)
        if unsupported:
            return self._result(
                "unsupported",
                schema_path,
                "schema",
                f"unsupported value schema keywords: {', '.join(unsupported)}",
            )

        if "contains" in schema:
            return self._matches_contains(value, schema.get("contains") or {}, schema_path)

        if "items" in schema and isinstance(value, list):
            item_schema = schema.get("items") or {}
            traces: List[ConditionTrace] = []
            deps: List[str] = []
            for idx, item in enumerate(value):
                child = self._matches_value_schema(
                    item,
                    item_schema,
                    f"{schema_path}.items[{idx}]",
                )
                traces.extend(child.traces)
                deps.extend(child.dependent_paths)
                if child.result != "true":
                    return ConditionEvaluation(child.result, traces, sorted(set(deps)))
            return ConditionEvaluation("true", traces, sorted(set(deps)))

        if "required" in schema and isinstance(value, dict):
            for name in schema.get("required") or []:
                text = str(name)
                if not self._has_value(value.get(text)):
                    return self._result(
                        "false",
                        schema_path,
                        "required",
                        f"object key '{text}' is missing or empty",
                    )

        if "properties" in schema and isinstance(value, dict):
            traces: List[ConditionTrace] = []
            deps: List[str] = []
            for name, predicate in (schema.get("properties") or {}).items():
                if name not in value:
                    continue
                child = self._matches_value_schema(
                    value.get(name),
                    predicate or {},
                    f"{schema_path}.properties.{name}",
                )
                traces.extend(child.traces)
                deps.extend(child.dependent_paths)
                if child.result != "true":
                    return ConditionEvaluation(child.result, traces, sorted(set(deps)))
            return ConditionEvaluation("true", traces, sorted(set(deps)))

        if "enum" in schema or "const" in schema:
            return self._matches_scalar_constraint(value, schema, schema_path)

        return self._result("true", schema_path, "schema", "supported value schema matched")

    def _matches_contains(
        self,
        value: Any,
        schema: Dict[str, Any],
        schema_path: str,
    ) -> ConditionEvaluation:
        if not isinstance(value, list):
            return self._result("false", schema_path, "contains", "value is not an array")
        saw_unknown = False
        traces: List[ConditionTrace] = []
        deps: List[str] = []
        for idx, item in enumerate(value):
            child = self._matches_value_schema(item, schema, f"{schema_path}[{idx}]")
            traces.extend(child.traces)
            deps.extend(child.dependent_paths)
            if child.result == "true":
                return ConditionEvaluation("true", traces, sorted(set(deps)))
            if child.is_unknown:
                saw_unknown = True
        return ConditionEvaluation("unknown" if saw_unknown else "false", traces, sorted(set(deps)))

    def _matches_scalar_constraint(
        self,
        value: Any,
        schema: Dict[str, Any],
        schema_path: str,
    ) -> ConditionEvaluation:
        scalar = self._scalar_value(value)
        if "const" in schema:
            expected = schema.get("const")
            return self._result(
                "true" if scalar == expected else "false",
                schema_path,
                "const",
                f"{scalar!r} {'==' if scalar == expected else '!='} {expected!r}",
            )
        enum = schema.get("enum")
        if enum is not None:
            return self._result(
                "true" if scalar in enum else "false",
                schema_path,
                "enum",
                f"{scalar!r} {'in' if scalar in enum else 'not in'} enum",
            )
        return self._result("true", schema_path, "schema", "no scalar constraint")

    @staticmethod
    def _has_value(value: Any) -> bool:
        if value in (None, "", []):
            return False
        if isinstance(value, list):
            return any(SchemaConditionEvaluatorV2._has_value(item) for item in value)
        if isinstance(value, dict):
            return any(v not in (None, "", []) for v in value.values())
        return True

    @staticmethod
    def _scalar_value(value: Any) -> Any:
        if isinstance(value, list) and value:
            return SchemaConditionEvaluatorV2._scalar_value(value[0])
        if isinstance(value, dict):
            if "value" in value:
                return value.get("value")
            if "name" in value:
                return value.get("name")
        return value

    @classmethod
    def _unsupported_keywords(cls, schema: Dict[str, Any]) -> List[str]:
        allowed = cls.SUPPORTED_SCHEMA_KEYS | cls.ANNOTATION_KEYS
        return sorted(str(key) for key in schema if key not in allowed)

    @staticmethod
    def _result(
        result: str,
        schema_path: str,
        operator: str,
        reason: str,
    ) -> ConditionEvaluation:
        return ConditionEvaluation(
            result,
            [ConditionTrace(schema_path=schema_path, operator=operator, result=result, reason=reason)],
            [],
        )
