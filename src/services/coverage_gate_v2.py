"""Tree-level coverage gate for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.services.requirement_models_v2 import (
    PayloadBuildPlan,
    RequirementNode,
    ResolutionNode,
)


@dataclass
class CoverageGateResultV2:
    """Tree-level coverage decision for one V2 payload plan."""

    blocked: bool = False
    covered_required_paths: List[str] = field(default_factory=list)
    missing_required_paths: List[str] = field(default_factory=list)
    low_confidence_required_paths: List[str] = field(default_factory=list)
    pending_review_paths: List[str] = field(default_factory=list)
    safe_default_paths: List[str] = field(default_factory=list)
    blocking_codes: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "blocked": self.blocked,
            "covered_required_paths": self.covered_required_paths,
            "missing_required_paths": self.missing_required_paths,
            "low_confidence_required_paths": self.low_confidence_required_paths,
            "pending_review_paths": self.pending_review_paths,
            "safe_default_paths": self.safe_default_paths,
            "blocking_codes": self.blocking_codes,
            "findings": self.findings,
        }


class CoverageGateV2:
    """Validate required tree coverage and path-level review/default policy."""

    def evaluate(
        self,
        requirement_root: RequirementNode,
        resolution_root: ResolutionNode | None,
        attributes: Dict[str, Any],
    ) -> CoverageGateResultV2:
        result = CoverageGateResultV2()
        resolution_index = self._index_resolutions(resolution_root)
        for requirement in requirement_root.children:
            self._evaluate_node(requirement, resolution_index, attributes, result)
        result.blocked = bool(result.blocking_codes)
        return result

    @staticmethod
    def apply_to_plan(
        plan: PayloadBuildPlan,
        result: CoverageGateResultV2,
    ) -> PayloadBuildPlan:
        """Copy coverage output into a PayloadBuildPlan contract."""
        plan.covered_required_paths = list(result.covered_required_paths)
        plan.missing_required_paths = list(result.missing_required_paths)
        plan.low_confidence_required_paths = list(result.low_confidence_required_paths)
        plan.pending_review_paths = list(result.pending_review_paths)
        plan.safe_default_paths = list(result.safe_default_paths)
        plan.findings.extend(result.findings)
        return plan

    def _evaluate_node(
        self,
        requirement: RequirementNode,
        resolution_index: Dict[str, ResolutionNode],
        attributes: Dict[str, Any],
        result: CoverageGateResultV2,
    ) -> None:
        if not requirement.required:
            return
        resolution = resolution_index.get(requirement.path_key)
        payload_value = self._payload_value(requirement, attributes)
        if not self._has_value(payload_value):
            self._mark_missing(result, requirement)
            return

        if requirement.shape == "measure":
            missing = [
                child
                for child in ("value", "unit")
                if child in requirement.required_children
                and not self._has_value(self._child_payload_value(payload_value, child))
            ]
            if missing:
                for child in missing:
                    self._mark_missing(result, requirement, child)
                return

        result.covered_required_paths.append(requirement.path_key)
        self._evaluate_resolution_policy(requirement, resolution, result)
        for child in requirement.children:
            self._evaluate_node(child, resolution_index, attributes, result)

    def _evaluate_resolution_policy(
        self,
        requirement: RequirementNode,
        resolution: ResolutionNode | None,
        result: CoverageGateResultV2,
    ) -> None:
        if resolution is None:
            return
        if resolution.value in (None, "") and resolution.children:
            return
        if self._is_pending_review(resolution):
            result.pending_review_paths.append(requirement.path_key)
            self._add_blocking(
                result,
                "NEEDS_REVIEW_REQUIRED_ATTRIBUTE",
                requirement.path_key,
                "Required path needs review approval",
            )
            return
        if self._is_low_confidence(resolution):
            result.low_confidence_required_paths.append(requirement.path_key)
            self._add_blocking(
                result,
                "LOW_CONFIDENCE_REQUIRED_ATTRIBUTE",
                requirement.path_key,
                "Required path resolved with low confidence",
            )
            return
        if resolution.source == "default" and resolution.safe_default:
            result.safe_default_paths.append(requirement.path_key)
        elif resolution.source == "default" and not resolution.safe_default:
            self._add_blocking(
                result,
                "UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE",
                requirement.path_key,
                "Required path resolved with a non-whitelisted default",
            )

    def _payload_value(self, requirement: RequirementNode, attributes: Dict[str, Any]) -> Any:
        parts = requirement.path_key.split(".")
        value = attributes.get(parts[0])
        for part in parts[1:]:
            value = self._child_payload_value(value, part)
        return value

    def _child_payload_value(self, value: Any, child_name: str) -> Any:
        if isinstance(value, list):
            values: List[Any] = []
            for item in value:
                if isinstance(item, list):
                    child_value = self._child_payload_value(item, child_name)
                    if isinstance(child_value, list):
                        values.extend(child_value)
                    elif child_value is not None:
                        values.append(child_value)
                elif isinstance(item, dict) and child_name in item:
                    values.append(item.get(child_name))
            return values
        if isinstance(value, dict):
            return value.get(child_name)
        return None

    @classmethod
    def _has_value(cls, value: Any) -> bool:
        if value in (None, "", []):
            return False
        if isinstance(value, list):
            return any(cls._has_value(item) for item in value)
        if isinstance(value, dict):
            return any(cls._has_value(item) for item in value.values())
        return True

    def _mark_missing(
        self,
        result: CoverageGateResultV2,
        requirement: RequirementNode,
        child_name: str | None = None,
    ) -> None:
        path_key = (
            f"{requirement.path_key}.{child_name}" if child_name else requirement.path_key
        )
        if path_key not in result.missing_required_paths:
            result.missing_required_paths.append(path_key)
        self._add_blocking(
            result,
            "MISSING_REQUIRED_ATTRIBUTE_RULE",
            path_key,
            "Required path has no resolved payload value",
        )

    @staticmethod
    def _is_pending_review(resolution: ResolutionNode) -> bool:
        return str(resolution.review_status or "").lower() in {"pending", "needs_review"}

    @staticmethod
    def _is_low_confidence(resolution: ResolutionNode) -> bool:
        if str(resolution.review_status or "").lower() in {
            "auto_approved",
            "completed",
            "approved",
        }:
            return False
        return resolution.confidence == "low" or bool(resolution.blocking)

    def _add_blocking(
        self,
        result: CoverageGateResultV2,
        code: str,
        path_key: str,
        message: str,
    ) -> None:
        if code not in result.blocking_codes:
            result.blocking_codes.append(code)
        result.findings.append(
            {
                "code": code,
                "path_key": path_key,
                "severity": "ERROR",
                "blocking": True,
                "message": message,
            }
        )

    @staticmethod
    def _index_resolutions(root: ResolutionNode | None) -> Dict[str, ResolutionNode]:
        if root is None:
            return {}
        index: Dict[str, ResolutionNode] = {}

        def visit(node: ResolutionNode) -> None:
            index[node.path_key] = node
            for child in node.children:
                visit(child)

        visit(root)
        return index
