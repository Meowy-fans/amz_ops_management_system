"""Apply Amazon 90220 learned paths onto V2 YAML attribute rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.services.feedback_learning_adapter_v2 import FeedbackLearningAdapterV2
from src.services.rule_field_mapper_v2 import RuleFieldMapperV2
from src.services.rule_tree_utils_v2 import (
    ensure_rule_at_path,
    get_rule_at_path,
    has_placeholder_source,
    replace_placeholder_sources,
)


@dataclass
class RuleFeedbackApplyResult:
    product_type: str
    learned_path_count: int
    added_path_count: int
    mapped_path_count: int
    added_paths: List[str] = field(default_factory=list)
    mapped_paths: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rules: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "learned_path_count": self.learned_path_count,
            "added_path_count": self.added_path_count,
            "mapped_path_count": self.mapped_path_count,
            "added_paths": self.added_paths,
            "mapped_paths": self.mapped_paths,
            "warnings": self.warnings,
        }


class RuleFeedbackAdapterV2:
    """Turn learned Amazon missing-required paths into YAML rule entries."""

    def __init__(
        self,
        db: Any = None,
        feedback_adapter: FeedbackLearningAdapterV2 | None = None,
        field_mapper: RuleFieldMapperV2 | None = None,
    ):
        self.db = db
        self.feedback_adapter = feedback_adapter or (
            FeedbackLearningAdapterV2(db=db) if db is not None else FeedbackLearningAdapterV2()
        )
        self.field_mapper = field_mapper or RuleFieldMapperV2(db=db)

    def apply_learned_paths(
        self,
        product_type: str,
        rules: Dict[str, Any],
        learned_paths: Optional[List[str]] = None,
        sample_skus: Optional[List[str]] = None,
    ) -> RuleFeedbackApplyResult:
        normalized = str(product_type or "").strip().upper()
        attributes = dict((rules.get("attributes") or {}))
        paths = list(learned_paths or self.feedback_adapter.get_learned_required_paths(normalized))
        added_paths: List[str] = []
        mapped_paths: List[str] = []
        warnings: List[str] = []

        for amazon_path in paths:
            yaml_path = self._resolve_yaml_path(attributes, amazon_path)
            if yaml_path is None:
                warnings.append(f"No YAML path resolved for learned attribute {amazon_path}")
                continue
            existing = get_rule_at_path(attributes, yaml_path)
            if existing is None:
                leaf = ensure_rule_at_path(attributes, yaml_path)
                leaf.setdefault("transform", "passthrough")
                proposals = self.field_mapper._propose_sources(
                    yaml_path,
                    [],
                    sample_skus or [],
                    normalized,
                    min_hit_rate=0.0,
                )
                if proposals:
                    leaf["sources"] = proposals
                    mapped_paths.append(yaml_path)
                else:
                    leaf["sources"] = [
                        self._feedback_placeholder_source(amazon_path, yaml_path)
                    ]
                    added_paths.append(yaml_path)
                continue
            if not has_placeholder_source(existing):
                continue
            proposals = self.field_mapper._propose_sources(
                yaml_path,
                [],
                sample_skus or [],
                normalized,
                min_hit_rate=0.0,
            )
            if proposals:
                replace_placeholder_sources(existing, proposals)
                mapped_paths.append(yaml_path)
            else:
                replace_placeholder_sources(
                    existing,
                    [self._feedback_placeholder_source(amazon_path, yaml_path)],
                )
                added_paths.append(yaml_path)

        merged = dict(rules)
        merged["attributes"] = attributes
        return RuleFeedbackApplyResult(
            product_type=normalized,
            learned_path_count=len(paths),
            added_path_count=len(added_paths),
            mapped_path_count=len(mapped_paths),
            added_paths=added_paths,
            mapped_paths=mapped_paths,
            warnings=warnings,
            rules=merged,
        )

    @classmethod
    def _resolve_yaml_path(cls, attributes: Dict[str, Any], amazon_path: str) -> str | None:
        text = str(amazon_path or "").strip()
        if not text:
            return None
        candidates = cls._path_candidates(text)
        for candidate in candidates:
            if get_rule_at_path(attributes, candidate) is not None:
                return candidate
        return candidates[0] if candidates else None

    @staticmethod
    def _path_candidates(amazon_path: str) -> List[str]:
        if "." in amazon_path:
            return [amazon_path, f"{amazon_path}.value"]
        tokens = [part for part in amazon_path.split("_") if part]
        if len(tokens) < 2:
            return [amazon_path, f"{amazon_path}.value"]
        candidates: List[str] = []
        for split_at in range(1, len(tokens)):
            prefix = ".".join(tokens[:split_at])
            suffix = ".".join(tokens[split_at:])
            candidates.append(f"{prefix}.{suffix}.value")
            candidates.append(f"{prefix}.{suffix}")
        candidates.append(amazon_path)
        return candidates

    @staticmethod
    def _feedback_placeholder_source(amazon_path: str, yaml_path: str) -> Dict[str, Any]:
        return {
            "default": None,
            "confidence": "low",
            "evidence": (
                f"Learned from Amazon 90220 ({amazon_path}); "
                f"review source mapping for {yaml_path}"
            ),
        }
