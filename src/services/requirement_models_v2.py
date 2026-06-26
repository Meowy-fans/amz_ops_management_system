"""Data contracts for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ConditionTrace:
    """Audit record for one schema condition evaluation."""

    schema_path: str
    operator: str
    result: str
    reason: str = ""
    dependent_paths: List[str] = field(default_factory=list)
    introduced_required_paths: List[str] = field(default_factory=list)
    non_applicable_required_paths: List[str] = field(default_factory=list)
    unknown_required_paths: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_path": self.schema_path,
            "operator": self.operator,
            "result": self.result,
            "reason": self.reason,
            "dependent_paths": self.dependent_paths,
            "introduced_required_paths": self.introduced_required_paths,
            "non_applicable_required_paths": self.non_applicable_required_paths,
            "unknown_required_paths": self.unknown_required_paths,
        }


@dataclass
class RequirementNode:
    """One node in the applicable Amazon schema requirement tree."""

    path_key: str
    schema_path: str
    name: str
    shape: str
    required: bool = False
    required_children: List[str] = field(default_factory=list)
    children: List["RequirementNode"] = field(default_factory=list)
    enum_values: List[str] = field(default_factory=list)
    unit_values: List[str] = field(default_factory=list)
    selectors: List[str] = field(default_factory=list)
    auto_fields: Dict[str, Any] = field(default_factory=dict)
    condition_trace: List[ConditionTrace] = field(default_factory=list)
    condition_state: str = "unconditional"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path_key": self.path_key,
            "schema_path": self.schema_path,
            "name": self.name,
            "shape": self.shape,
            "required": self.required,
            "required_children": self.required_children,
            "children": [child.as_dict() for child in self.children],
            "enum_values": self.enum_values,
            "unit_values": self.unit_values,
            "selectors": self.selectors,
            "auto_fields": self.auto_fields,
            "condition_trace": [trace.as_dict() for trace in self.condition_trace],
            "condition_state": self.condition_state,
        }


@dataclass
class RequirementTree:
    """Applicable requirement tree plus condition audit metadata."""

    product_type: str
    root: RequirementNode
    required_paths: List[str]
    condition_traces: List[ConditionTrace] = field(default_factory=list)
    non_applicable_required_paths: List[str] = field(default_factory=list)
    unknown_required_paths: List[str] = field(default_factory=list)
    iteration_count: int = 1
    non_converged: bool = False
    path_key_version: str = "v2_path_keys_2026_06"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "root": self.root.as_dict(),
            "required_paths": self.required_paths,
            "condition_traces": [trace.as_dict() for trace in self.condition_traces],
            "non_applicable_required_paths": self.non_applicable_required_paths,
            "unknown_required_paths": self.unknown_required_paths,
            "iteration_count": self.iteration_count,
            "non_converged": self.non_converged,
            "path_key_version": self.path_key_version,
        }


@dataclass
class ResolutionNode:
    """Path-level resolution state placeholder for later V2 slices."""

    path_key: str
    value: Any = None
    source: str = ""
    evidence: str = ""
    confidence: str = "low"
    confidence_score: int | None = None
    review_status: str = ""
    review_route: str = ""
    safe_default: bool = False
    blocking: bool = False
    blocking_codes: List[str] = field(default_factory=list)
    children: List["ResolutionNode"] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path_key": self.path_key,
            "value": self.value,
            "source": self.source,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "review_status": self.review_status,
            "review_route": self.review_route,
            "safe_default": self.safe_default,
            "blocking": self.blocking,
            "blocking_codes": self.blocking_codes,
            "children": [child.as_dict() for child in self.children],
        }


@dataclass
class PayloadBuildPlan:
    """V2 payload build plan contract placeholder for later slices."""

    sku: str
    product_type: str
    attributes: Dict[str, Any]
    requirement_tree: RequirementTree
    resolution_tree: ResolutionNode | None = None
    covered_required_paths: List[str] = field(default_factory=list)
    missing_required_paths: List[str] = field(default_factory=list)
    low_confidence_required_paths: List[str] = field(default_factory=list)
    pending_review_paths: List[str] = field(default_factory=list)
    safe_default_paths: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku,
            "product_type": self.product_type,
            "attributes": self.attributes,
            "requirement_tree": self.requirement_tree.as_dict(),
            "resolution_tree": (
                self.resolution_tree.as_dict() if self.resolution_tree else None
            ),
            "covered_required_paths": self.covered_required_paths,
            "missing_required_paths": self.missing_required_paths,
            "low_confidence_required_paths": self.low_confidence_required_paths,
            "pending_review_paths": self.pending_review_paths,
            "safe_default_paths": self.safe_default_paths,
            "findings": self.findings,
        }
