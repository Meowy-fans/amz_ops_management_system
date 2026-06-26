"""Path-level confidence scorer for V2 ResolutionTree."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

from src.models.amazon_listing import AmazonListingDraft
from src.services.requirement_models_v2 import RequirementNode, ResolutionNode


@dataclass
class PathConfidenceScore:
    """V2 path-level confidence score with parent aggregation."""

    path_key: str
    score: int
    route: str
    signals: Dict[str, int] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)


class ConfidenceScorerV2:
    """Score path-level confidence and aggregate parent review state."""

    DEFAULT_POLICY = {
        "enabled": True,
        "enabled_product_types": ["CHAIR"],
        "thresholds": {"auto_approved": 55, "ai_agent": 35},
        "weights": {
            "evidence_context_match": 45,
            "evidence_min_length": 10,
            "enum_valid": 15,
            "llm_confidence_not_low": 10,
            "history_accuracy": 20,
        },
        "evidence_min_length": 20,
        "history_min_samples": 10,
    }

    _SENSITIVE_PATH_ROOTS = (
        "brand",
        "manufacturer",
        "item_identifier",
        "product_identifier",
        "compliance",
        "certification",
    )

    _PARENT_SHAPES = {"root", "object", "nested_object", "array_object", "measure"}

    _ROUTE_PRIORITY = {"auto_approved": 0, "ai_agent": 1, "human": 2}

    def __init__(
        self,
        schema_service: Any = None,
        policy_path: Path | None = None,
        policy: Dict[str, Any] | None = None,
        history_provider: Any = None,
        context_provider: Any = None,
    ):
        self.schema_service = schema_service
        self.policy_path = policy_path or (
            Path(__file__).resolve().parents[2]
            / "config"
            / "listing_gates"
            / "review_policy.yaml"
        )
        self.policy = self._load_policy(policy)
        self.history_provider = history_provider
        self.context_provider = context_provider

    def score_tree(
        self,
        resolution_root: ResolutionNode,
        draft: AmazonListingDraft,
        requirement_root: RequirementNode,
    ) -> None:
        """Score all nodes in place. Walks tree, scores leaves, aggregates parents."""
        for resolution, requirement in self._walk(resolution_root, requirement_root):
            score = self.score_node(resolution, draft, requirement)
            resolution.confidence_score = score.score
            resolution.review_route = score.route

    def score_node(
        self,
        resolution: ResolutionNode,
        draft: AmazonListingDraft,
        requirement: RequirementNode,
    ) -> PathConfidenceScore:
        if not self._policy_enabled_for(draft.product_type):
            return PathConfidenceScore(
                path_key=resolution.path_key,
                score=0,
                route="human",
                reasons=["review_policy_disabled"],
            )
        if self._is_sensitive(resolution.path_key):
            return PathConfidenceScore(
                path_key=resolution.path_key,
                score=0,
                route="human",
                reasons=["sensitive_path"],
            )
        if requirement.shape in self._PARENT_SHAPES:
            return self._score_parent(resolution, requirement)
        return self._score_leaf(resolution, draft, requirement)

    def _score_leaf(
        self,
        resolution: ResolutionNode,
        draft: AmazonListingDraft,
        requirement: RequirementNode,
    ) -> PathConfidenceScore:
        if resolution.value in (None, ""):
            return PathConfidenceScore(
                path_key=resolution.path_key,
                score=0,
                route="human",
                reasons=["missing_value"],
            )
        if resolution.safe_default:
            return PathConfidenceScore(
                path_key=resolution.path_key,
                score=100,
                route="auto_approved",
                reasons=["safe_default"],
            )
        signals, reasons = self._collect_leaf_signals(resolution, draft, requirement)
        total = min(100, sum(signals.values()))
        return PathConfidenceScore(
            path_key=resolution.path_key,
            score=total,
            route=self._route(total),
            signals=signals,
            reasons=reasons,
        )

    def _collect_leaf_signals(
        self,
        resolution: ResolutionNode,
        draft: AmazonListingDraft,
        requirement: RequirementNode,
    ) -> tuple[Dict[str, int], List[str]]:
        signals: Dict[str, int] = {}
        reasons: List[str] = []
        weights = self.policy.get("weights") or {}
        evidence = str(resolution.evidence or "").strip()
        context = self._context_text(draft, requirement)

        if evidence and evidence.casefold() in context.casefold():
            signals["evidence_context_match"] = int(
                weights.get("evidence_context_match", 45)
            )
        else:
            reasons.append("evidence_not_in_context")

        min_length = int(self.policy.get("evidence_min_length", 20))
        if len(evidence) >= min_length:
            signals["evidence_min_length"] = int(weights.get("evidence_min_length", 10))
        else:
            reasons.append("evidence_too_short")

        if self._enum_value_is_valid(requirement, resolution.value):
            signals["enum_valid"] = int(weights.get("enum_valid", 15))

        if str(resolution.confidence or "").lower() != "low":
            signals["llm_confidence_not_low"] = int(
                weights.get("llm_confidence_not_low", 10)
            )

        history_points = self._history_points(draft.product_type, resolution.path_key)
        if history_points:
            signals["history_accuracy"] = history_points
        return signals, reasons

    def _score_parent(
        self,
        resolution: ResolutionNode,
        requirement: RequirementNode,
    ) -> PathConfidenceScore:
        if not resolution.children:
            return PathConfidenceScore(
                path_key=resolution.path_key,
                score=0,
                route="human",
                reasons=["parent_without_children"],
            )
        child_priorities = [
            self._ROUTE_PRIORITY.get(child.review_route or "human", 2)
            for child in resolution.children
        ]
        worst = max(child_priorities)
        route = next(
            key for key, priority in self._ROUTE_PRIORITY.items() if priority == worst
        )
        child_scores = [child.confidence_score or 0 for child in resolution.children]
        score = min(child_scores) if child_scores else 0
        return PathConfidenceScore(
            path_key=resolution.path_key,
            score=score,
            route=route,
            reasons=["aggregated_from_children"],
        )

    def _policy_enabled_for(self, product_type: str) -> bool:
        if not bool(self.policy.get("enabled", True)):
            return False
        enabled = [
            str(item).upper()
            for item in (self.policy.get("enabled_product_types") or [])
            if str(item or "").strip()
        ]
        return not enabled or str(product_type or "").upper() in enabled

    def _route(self, score: int) -> str:
        thresholds = self.policy.get("thresholds") or {}
        if score >= int(thresholds.get("auto_approved", 55)):
            return "auto_approved"
        if score >= int(thresholds.get("ai_agent", 35)):
            return "ai_agent"
        return "human"

    def _is_sensitive(self, path_key: str) -> bool:
        name = str(path_key or "").strip().lower()
        root = name.split(".")[0].split("{")[0]
        return root in self._SENSITIVE_PATH_ROOTS

    def _enum_value_is_valid(self, requirement: RequirementNode, value: Any) -> bool:
        if not requirement.enum_values:
            return False
        if isinstance(value, list):
            candidates = [str(item).strip().casefold() for item in value]
        else:
            candidates = [str(value or "").strip().casefold()]
        allowed = {str(item).strip().casefold() for item in requirement.enum_values}
        return all(item in allowed for item in candidates if item)

    def _history_points(self, product_type: str, path_key: str) -> int:
        provider = self.history_provider
        if provider is None or not hasattr(provider, "get_attribute_accuracy"):
            return 0
        min_samples = int(self.policy.get("history_min_samples", 10))
        try:
            accuracy = provider.get_attribute_accuracy(product_type, path_key, min_samples)
        except Exception:
            return 0
        if accuracy is None:
            return 0
        return int(float(accuracy) * int((self.policy.get("weights") or {}).get("history_accuracy", 20)))

    def _context_text(
        self,
        draft: AmazonListingDraft,
        requirement: RequirementNode,
    ) -> str:
        if self.context_provider is not None:
            try:
                return str(self.context_provider(draft, requirement) or "")
            except Exception:
                return ""
        parts: List[str] = []
        content = draft.content
        if content is not None:
            if content.title:
                parts.append(content.title)
            if content.description:
                parts.append(content.description)
            if content.bullets:
                parts.extend(str(item) for item in content.bullets)
            if content.search_terms:
                parts.append(content.search_terms)
            if content.generic_keyword:
                parts.append(content.generic_keyword)
        product = draft.standard_product
        if product is not None:
            attrs = getattr(product, "attributes", None) or {}
            if isinstance(attrs, dict):
                parts.extend(str(item) for item in attrs.values())
        return "\n".join(parts)

    def _walk(
        self,
        resolution: ResolutionNode,
        requirement: RequirementNode,
    ):
        """Yield (resolution, requirement) pairs in post-order (children first)."""
        res_by_key = {child.path_key: child for child in resolution.children}
        for req_child in requirement.children:
            res_child = res_by_key.get(req_child.path_key)
            if res_child is not None:
                yield from self._walk(res_child, req_child)
        yield resolution, requirement

    def _load_policy(self, policy: Dict[str, Any] | None) -> Dict[str, Any]:
        merged = self._deep_merge(dict(self.DEFAULT_POLICY), policy or {})
        if not policy and self.policy_path.exists():
            with open(self.policy_path, "r", encoding="utf-8") as f:
                file_policy = yaml.safe_load(f) or {}
            merged = self._deep_merge(merged, file_policy)
        return merged

    @classmethod
    def _deep_merge(cls, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = cls._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
