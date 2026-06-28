"""Layer 1 YAML rule review for Listing Rule Authoring V2."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from src.repositories.pending_rule_review_repository import PendingRuleReviewRepository
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.rule_tree_utils_v2 import (
    attribute_root,
    get_rule_at_path,
    has_placeholder_source,
    iter_leaf_rules,
    remove_rule_at_path,
)


RULE_REVIEW_DECISIONS = frozenset(
    {
        "safe_default",
        "manual_review",
        "omit_attribute",
        "coverage_ignore",
        "waived",
    }
)

BLOCKING_ISSUE_TYPES = frozenset(
    {
        "todo_placeholder",
        "unsafe_default",
        "structural_parent_sources",
        "missing_dimension_strategy",
        "risk_partial_emit",
    }
)

DECISION_RESOLVES: Dict[str, Set[str]] = {
    "safe_default": {"unsafe_default"},
    "manual_review": {"todo_placeholder"},
    "omit_attribute": {"risk_partial_emit", "structural_parent_sources"},
    "coverage_ignore": {"risk_partial_emit"},
}


@dataclass
class RuleReviewItem:
    product_type: str
    path_key: str
    issue_type: str
    detail: str
    blocking: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "path_key": self.path_key,
            "issue_type": self.issue_type,
            "detail": self.detail,
            "blocking": self.blocking,
        }


@dataclass
class RuleReviewReport:
    product_type: str
    leaf_count: int
    placeholder_leaf_count: int
    items: List[RuleReviewItem] = field(default_factory=list)

    @property
    def blocking_item_count(self) -> int:
        return sum(1 for item in self.items if item.blocking)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "leaf_count": self.leaf_count,
            "placeholder_leaf_count": self.placeholder_leaf_count,
            "item_count": len(self.items),
            "blocking_item_count": self.blocking_item_count,
            "items": [item.as_dict() for item in self.items],
        }


@dataclass
class RuleApproveResult:
    product_type: str
    path_key: str
    decision: str
    reviewer: str
    written: bool
    yaml_path: Optional[str]
    resolved_issue_types: List[str]
    patch_summary: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "path_key": self.path_key,
            "decision": self.decision,
            "reviewer": self.reviewer,
            "written": self.written,
            "yaml_path": self.yaml_path,
            "resolved_issue_types": self.resolved_issue_types,
            "patch_summary": self.patch_summary,
        }


class RuleReviewServiceV2:
    """Scan and approve YAML rules for Layer 1 review gaps."""

    def __init__(
        self,
        rule_loader: AttributeRuleLoader | None = None,
        review_repo: PendingRuleReviewRepository | None = None,
    ):
        self.rule_loader = rule_loader or AttributeRuleLoader()
        self.review_repo = review_repo

    def review_category(
        self,
        product_type: str,
        *,
        db: Session | None = None,
    ) -> RuleReviewReport:
        normalized = str(product_type or "").strip().upper()
        rules = self.rule_loader.load(normalized)
        attributes = rules.get("attributes") or {}
        items = self._scan_rules(normalized, rules, attributes)
        suppressed = self._suppressed_issue_keys(normalized, db)
        filtered = [
            item
            for item in items
            if (item.path_key, item.issue_type) not in suppressed
            and not self._yaml_suppresses_issue(attributes, item)
        ]
        placeholder_leaf_count = sum(
            1 for _, rule in iter_leaf_rules(attributes) if has_placeholder_source(rule)
        )
        return RuleReviewReport(
            product_type=normalized,
            leaf_count=sum(1 for _ in iter_leaf_rules(attributes)),
            placeholder_leaf_count=placeholder_leaf_count,
            items=filtered,
        )

    def approve_rule(
        self,
        *,
        product_type: str,
        path_key: str,
        decision: str,
        reviewer: str,
        write: bool = False,
        issue_type: Optional[str] = None,
        detail: Optional[str] = None,
        db: Session | None = None,
    ) -> RuleApproveResult:
        normalized = str(product_type or "").strip().upper()
        normalized_path = str(path_key or "").strip()
        normalized_decision = str(decision or "").strip().lower()
        normalized_reviewer = str(reviewer or "").strip()
        if not normalized_path:
            raise ValueError("path_key is required")
        if normalized_decision not in RULE_REVIEW_DECISIONS:
            raise ValueError(
                f"decision must be one of: {', '.join(sorted(RULE_REVIEW_DECISIONS))}"
            )
        if not normalized_reviewer:
            raise ValueError("reviewer is required")

        rules = copy.deepcopy(self.rule_loader.load(normalized))
        attributes = rules.setdefault("attributes", {})
        patch_summary = self._apply_decision(rules, attributes, normalized_path, normalized_decision)

        report = self.review_category(normalized, db=db)
        open_items = [
            item
            for item in report.items
            if item.path_key == normalized_path
            and (issue_type is None or item.issue_type == issue_type)
        ]
        resolved_issue_types = (
            [issue_type]
            if issue_type
            else [item.issue_type for item in open_items]
        )
        if not resolved_issue_types:
            resolved_issue_types = [self._default_issue_type(normalized_decision)]

        repo = self._repo(db)
        if repo is not None:
            for resolved_issue in resolved_issue_types:
                repo.upsert_decision(
                    category=normalized,
                    path_key=normalized_path,
                    issue_type=resolved_issue,
                    decision=normalized_decision,
                    reviewer=normalized_reviewer,
                    detail=detail,
                    patch_summary=patch_summary,
                )

        yaml_path = None
        if write:
            config_dir = getattr(self.rule_loader, "config_dir", None)
            yaml_path = str(
                self._write_rules(
                    normalized,
                    rules,
                    written_by="approve_rule_v2",
                    config_dir=config_dir,
                )
            )

        return RuleApproveResult(
            product_type=normalized,
            path_key=normalized_path,
            decision=normalized_decision,
            reviewer=normalized_reviewer,
            written=bool(write),
            yaml_path=yaml_path,
            resolved_issue_types=resolved_issue_types,
            patch_summary=patch_summary,
        )

    def _scan_rules(
        self,
        normalized: str,
        rules: Dict[str, Any],
        attributes: Dict[str, Any],
    ) -> List[RuleReviewItem]:
        items: List[RuleReviewItem] = []

        for path_key, rule in iter_leaf_rules(attributes):
            if has_placeholder_source(rule):
                items.append(
                    RuleReviewItem(
                        product_type=normalized,
                        path_key=path_key,
                        issue_type="todo_placeholder",
                        detail="Leaf source chain still contains TODO placeholder",
                    )
                )
            for source in rule.get("sources") or []:
                if source.get("inherited_from"):
                    items.append(
                        RuleReviewItem(
                            product_type=normalized,
                            path_key=path_key,
                            issue_type="inherited_source",
                            detail=(
                                f"Inherited from {source['inherited_from']}; "
                                "review for category fit"
                            ),
                            blocking=False,
                        )
                    )
                if (
                    "default" in source
                    and source.get("default") is not None
                    and not source.get("safe_default")
                    and source.get("confidence", "low") != "high"
                ):
                    items.append(
                        RuleReviewItem(
                            product_type=normalized,
                            path_key=path_key,
                            issue_type="unsafe_default",
                            detail="Default present without safe_default whitelist",
                        )
                    )

        for attr_name, rule in attributes.items():
            children = rule.get("children") or {}
            sources = rule.get("sources") or []
            if children and sources:
                items.append(
                    RuleReviewItem(
                        product_type=normalized,
                        path_key=attr_name,
                        issue_type="structural_parent_sources",
                        detail=(
                            "Structural parent has parent-level sources; prefer children only"
                        ),
                    )
                )

        if not rules.get("dimension_strategy"):
            schema_attrs = {
                name
                for name, block in attributes.items()
                if name.startswith("item_depth") or name == "item_depth_width_height"
            }
            if schema_attrs:
                items.append(
                    RuleReviewItem(
                        product_type=normalized,
                        path_key="(root)",
                        issue_type="missing_dimension_strategy",
                        detail="Dimension attributes present but dimension_strategy is unset",
                    )
                )

        ignored_roots = {
            str(name)
            for name in (rules.get("coverage_ignore_required") or [])
            if str(name or "").strip()
        }
        for attr_name in sorted(ignored_roots):
            if attr_name in attributes:
                items.append(
                    RuleReviewItem(
                        product_type=normalized,
                        path_key=attr_name,
                        issue_type="risk_partial_emit",
                        detail=(
                            "coverage_ignore_required root still has attributes block; "
                            "omit attribute to avoid partial emit (99022)"
                        ),
                    )
                )
        return items

    def _suppressed_issue_keys(
        self,
        category: str,
        db: Session | None,
    ) -> Set[Tuple[str, str]]:
        repo = self._repo(db)
        if repo is None:
            return set()
        suppressed: Set[Tuple[str, str]] = set()
        for row in repo.list_decisions(category):
            decision = str(row.get("decision") or "")
            path_key = str(row.get("path_key") or "")
            issue = str(row.get("issue_type") or "")
            if decision == "waived":
                suppressed.add((path_key, issue))
                continue
            for resolved in DECISION_RESOLVES.get(decision, set()):
                suppressed.add((path_key, resolved))
        return suppressed

    @staticmethod
    def _yaml_suppresses_issue(attributes: Dict[str, Any], item: RuleReviewItem) -> bool:
        if item.issue_type != "todo_placeholder":
            return False
        rule = get_rule_at_path(attributes, item.path_key) or {}
        layer1 = rule.get("layer1_review") or {}
        return str(layer1.get("route") or "") == "manual"

    def _apply_decision(
        self,
        rules: Dict[str, Any],
        attributes: Dict[str, Any],
        path_key: str,
        decision: str,
    ) -> Dict[str, Any]:
        if decision == "safe_default":
            return self._apply_safe_default(attributes, path_key)
        if decision == "manual_review":
            return self._apply_manual_review(attributes, path_key)
        if decision == "omit_attribute":
            return self._apply_omit_attribute(attributes, path_key)
        if decision == "coverage_ignore":
            return self._apply_coverage_ignore(rules, attributes, path_key)
        return {"waived": True, "path_key": path_key}

    @staticmethod
    def _apply_safe_default(attributes: Dict[str, Any], path_key: str) -> Dict[str, Any]:
        rule = get_rule_at_path(attributes, path_key)
        if rule is None:
            raise ValueError(f"path_key not found in rules: {path_key}")
        updated = 0
        for source in rule.get("sources") or []:
            if "default" in source and source.get("default") is not None:
                source["safe_default"] = True
                source.setdefault("confidence", "medium")
                updated += 1
        if updated == 0:
            raise ValueError(f"No default source to whitelist at path_key: {path_key}")
        return {"safe_default_sources": updated}

    @staticmethod
    def _apply_manual_review(attributes: Dict[str, Any], path_key: str) -> Dict[str, Any]:
        rule = get_rule_at_path(attributes, path_key)
        if rule is None:
            raise ValueError(f"path_key not found in rules: {path_key}")
        rule["layer1_review"] = {"route": "manual", "decided": True}
        return {"layer1_review": "manual"}

    @staticmethod
    def _apply_omit_attribute(attributes: Dict[str, Any], path_key: str) -> Dict[str, Any]:
        root = attribute_root(path_key)
        removed = remove_rule_at_path(attributes, path_key)
        if not removed and root in attributes:
            removed = attributes.pop(root, None) is not None
        if not removed:
            raise ValueError(f"Nothing removed for path_key: {path_key}")
        return {"removed_path_key": path_key, "removed_root": root}

    @staticmethod
    def _apply_coverage_ignore(
        rules: Dict[str, Any],
        attributes: Dict[str, Any],
        path_key: str,
    ) -> Dict[str, Any]:
        root = attribute_root(path_key)
        ignored = list(rules.get("coverage_ignore_required") or [])
        if root not in ignored:
            ignored.append(root)
            rules["coverage_ignore_required"] = ignored
        removed = False
        if root in attributes:
            del attributes[root]
            removed = True
        return {
            "coverage_ignore_required": ignored,
            "removed_attribute_block": removed,
            "root": root,
        }

    @staticmethod
    def _default_issue_type(decision: str) -> str:
        mapping = {
            "safe_default": "unsafe_default",
            "manual_review": "todo_placeholder",
            "omit_attribute": "risk_partial_emit",
            "coverage_ignore": "risk_partial_emit",
            "waived": "waived",
        }
        return mapping.get(decision, decision)

    def _repo(self, db: Session | None) -> PendingRuleReviewRepository | None:
        if self.review_repo is not None:
            return self.review_repo
        if db is None:
            return None
        return PendingRuleReviewRepository(db)

    @staticmethod
    def _write_rules(product_type: str, rules: Dict[str, Any], *, written_by: str, config_dir=None):
        from pathlib import Path

        from src.services.attribute_rule_loader import AttributeRuleLoader
        from src.services.rule_yaml_write_guard import write_rule_yaml

        loader = AttributeRuleLoader()
        base_dir = Path(config_dir) if config_dir is not None else loader.config_dir
        target_path = base_dir / f"{product_type.lower()}.yaml"
        write_rule_yaml(target_path, rules, product_type=product_type, written_by=written_by)
        return target_path
