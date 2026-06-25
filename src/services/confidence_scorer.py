"""Score evidence-grounded confidence for required LLM attributes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

from src.models.amazon_listing import AmazonListingDraft
from src.services.attribute_resolver import AttributeResolution
from src.services.llm_attribute_extractor import LLMAttributeExtractor


@dataclass
class ConfidenceScore:
    """Review routing result for one resolved attribute."""

    score: int
    route: str
    signals: Dict[str, int] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)


class ConfidenceScorer:
    """Scores whether a required LLM value can bypass manual review."""

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
    _SENSITIVE_MARKERS = LLMAttributeExtractor._SENSITIVE_MARKERS

    def __init__(
        self,
        schema_service: Any = None,
        policy_path: Path | None = None,
        policy: Dict[str, Any] | None = None,
        history_provider: Any = None,
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

    def score(
        self,
        resolution: AttributeResolution,
        draft: AmazonListingDraft,
    ) -> ConfidenceScore:
        if not self._policy_enabled_for(draft.product_type):
            return ConfidenceScore(0, "human", reasons=["review_policy_disabled"])
        if self._is_sensitive(resolution.attribute):
            return ConfidenceScore(0, "human", reasons=["sensitive_attribute"])
        if resolution.shape in {"object", "nested_object", "measure"}:
            return ConfidenceScore(0, "human", reasons=["unsupported_shape"])

        signals: Dict[str, int] = {}
        reasons: List[str] = []
        weights = self.policy.get("weights") or {}
        evidence = str(resolution.evidence or "").strip()
        context = self.context_text(draft, resolution.attribute)

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

        if self._enum_value_is_valid(draft.product_type, resolution.attribute, resolution.value):
            signals["enum_valid"] = int(weights.get("enum_valid", 15))

        if str(resolution.confidence or "").lower() != "low":
            signals["llm_confidence_not_low"] = int(
                weights.get("llm_confidence_not_low", 10)
            )

        history_points = self._history_points(draft.product_type, resolution.attribute)
        if history_points:
            signals["history_accuracy"] = history_points

        total = min(100, sum(signals.values()))
        return ConfidenceScore(
            score=total,
            route=self._route(total),
            signals=signals,
            reasons=reasons,
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

    def _enum_value_is_valid(
        self,
        product_type: str,
        attribute: str,
        value: Any,
    ) -> bool:
        if self.schema_service is None:
            return False
        try:
            values = self.schema_service.get_cached_valid_values(product_type, attribute) or []
        except Exception:
            return False
        if not values:
            return False
        if isinstance(value, list):
            candidates = [str(item).strip().casefold() for item in value]
        else:
            candidates = [str(value or "").strip().casefold()]
        allowed = {str(item).strip().casefold() for item in values}
        return all(item in allowed for item in candidates if item)

    def _history_points(self, product_type: str, attribute: str) -> int:
        provider = self.history_provider
        if provider is None or not hasattr(provider, "get_attribute_accuracy"):
            return 0
        min_samples = int(self.policy.get("history_min_samples", 10))
        try:
            accuracy = provider.get_attribute_accuracy(product_type, attribute, min_samples)
        except Exception:
            return 0
        if accuracy is None:
            return 0
        return int(float(accuracy) * int((self.policy.get("weights") or {}).get("history_accuracy", 20)))

    @staticmethod
    def context_text(draft: AmazonListingDraft, attribute: str) -> str:
        context = LLMAttributeExtractor._context(draft, attribute, {}, [])
        parts: List[str] = []
        for value in context.values():
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            elif isinstance(value, dict):
                parts.extend(str(item) for item in value.values())
            else:
                parts.append(str(value))
        return "\n".join(parts)

    @classmethod
    def _is_sensitive(cls, attribute: str) -> bool:
        name = str(attribute or "").strip().lower()
        return any(marker in name for marker in cls._SENSITIVE_MARKERS)

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
