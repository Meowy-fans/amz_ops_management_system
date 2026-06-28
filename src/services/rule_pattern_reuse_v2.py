"""Copy proven source chains across categories with isomorphic schema subtrees."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from src.services.rule_tree_utils_v2 import (
    has_placeholder_source,
    iter_leaf_rules,
    replace_placeholder_sources,
)


@dataclass
class RulePatternReuseResult:
    product_type: str
    reference_product_type: str
    candidate_leaf_count: int
    reused_leaf_count: int
    reused_paths: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rules: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "reference_product_type": self.reference_product_type,
            "candidate_leaf_count": self.candidate_leaf_count,
            "reused_leaf_count": self.reused_leaf_count,
            "reused_paths": self.reused_paths,
            "warnings": self.warnings,
        }


class RulePatternReuseV2:
    """Reuse leaf source chains when target and reference share path_key structure."""

    def reuse_patterns(
        self,
        product_type: str,
        rules: Dict[str, Any],
        reference_rules: Dict[str, Any],
        reference_product_type: str,
    ) -> RulePatternReuseResult:
        normalized = str(product_type or "").strip().upper()
        reference_name = str(reference_product_type or "").strip().upper()
        target_attributes = dict((rules.get("attributes") or {}))
        reference_attributes = dict((reference_rules.get("attributes") or {}))

        reference_by_path = {
            path_key: rule for path_key, rule in iter_leaf_rules(reference_attributes)
        }
        reference_signatures = {
            path_key: self._leaf_signature(path_key, rule)
            for path_key, rule in reference_by_path.items()
        }
        signature_to_paths: Dict[Tuple[Any, ...], List[str]] = {}
        for path_key, signature in reference_signatures.items():
            signature_to_paths.setdefault(signature, []).append(path_key)

        reused_paths: List[str] = []
        candidate_leaf_count = 0
        warnings: List[str] = []

        for path_key, target_rule in iter_leaf_rules(target_attributes):
            if not has_placeholder_source(target_rule):
                continue
            candidate_leaf_count += 1
            reference_rule = reference_by_path.get(path_key)
            if reference_rule is None or has_placeholder_source(reference_rule):
                signature = self._leaf_signature(path_key, target_rule)
                fallback_paths = signature_to_paths.get(signature) or []
                for fallback_path in fallback_paths:
                    reference_rule = reference_by_path.get(fallback_path)
                    if reference_rule and not has_placeholder_source(reference_rule):
                        warnings.append(
                            f"Reused {fallback_path} sources for {path_key} via subtree signature"
                        )
                        break
            if reference_rule is None or has_placeholder_source(reference_rule):
                continue
            copied_sources = copy.deepcopy(reference_rule.get("sources") or [])
            for source in copied_sources:
                source["inherited_from"] = reference_name
            replace_placeholder_sources(target_rule, copied_sources)
            reused_paths.append(path_key)

        merged = dict(rules)
        merged["attributes"] = target_attributes
        return RulePatternReuseResult(
            product_type=normalized,
            reference_product_type=reference_name,
            candidate_leaf_count=candidate_leaf_count,
            reused_leaf_count=len(reused_paths),
            reused_paths=reused_paths,
            warnings=warnings,
            rules=merged,
        )

    @staticmethod
    def _leaf_signature(path_key: str, rule: Dict[str, Any]) -> Tuple[Any, ...]:
        parent = ".".join(path_key.split(".")[:-1])
        leaf_name = path_key.split(".")[-1]
        return (
            parent,
            leaf_name,
            rule.get("shape"),
            rule.get("transform"),
        )
