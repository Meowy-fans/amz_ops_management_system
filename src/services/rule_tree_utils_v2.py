"""Shared helpers for walking and updating V2 attribute rule trees."""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Tuple


def iter_leaf_rules(
    attributes: Dict[str, Any],
    prefix: str = "",
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield (path_key, rule_dict) for every leaf rule node."""
    for name, rule in (attributes or {}).items():
        if not isinstance(rule, dict):
            continue
        path_key = f"{prefix}.{name}" if prefix else name
        children = rule.get("children") or {}
        if children:
            yield from iter_leaf_rules(children, path_key)
            continue
        yield path_key, rule


def get_rule_at_path(attributes: Dict[str, Any], path_key: str) -> Dict[str, Any] | None:
    parts = str(path_key or "").split(".")
    if not parts:
        return None
    rule = (attributes or {}).get(parts[0])
    if rule is None:
        return None
    for part in parts[1:]:
        if not isinstance(rule, dict):
            return None
        children = rule.get("children") or {}
        rule = children.get(part)
        if rule is None:
            return None
    return rule if isinstance(rule, dict) else None


def ensure_rule_at_path(attributes: Dict[str, Any], path_key: str) -> Dict[str, Any]:
    """Create intermediate object/measure nodes if missing."""
    parts = str(path_key or "").split(".")
    if not parts:
        raise ValueError("path_key is required")
    current = attributes.setdefault(parts[0], {})
    if len(parts) == 1:
        return current if isinstance(current, dict) else {}
    if not isinstance(current, dict):
        current = {}
        attributes[parts[0]] = current
    node = current
    for part in parts[1:-1]:
        children = node.setdefault("children", {})
        child = children.setdefault(part, {"shape": "object", "transform": "passthrough"})
        if not isinstance(child, dict):
            child = {}
            children[part] = child
        node = child
    children = node.setdefault("children", {})
    leaf_name = parts[-1]
    leaf = children.setdefault(leaf_name, {})
    if not isinstance(leaf, dict):
        leaf = {}
        children[leaf_name] = leaf
    return leaf


def has_placeholder_source(rule: Dict[str, Any]) -> bool:
    for source in rule.get("sources") or []:
        evidence = str(source.get("evidence") or "")
        if evidence.startswith("TODO:"):
            return True
    return not rule.get("sources")


def count_placeholder_leaves(attributes: Dict[str, Any]) -> int:
    return sum(1 for _, rule in iter_leaf_rules(attributes) if has_placeholder_source(rule))


def replace_placeholder_sources(
    rule: Dict[str, Any],
    sources: List[Dict[str, Any]],
) -> None:
    kept = [
        source
        for source in (rule.get("sources") or [])
        if source.get("llm") or source.get("safe_default")
    ]
    rule["sources"] = kept + list(sources)


def remove_rule_at_path(attributes: Dict[str, Any], path_key: str) -> bool:
    """Remove a rule node; returns True when something was deleted."""
    parts = [part for part in str(path_key or "").split(".") if part]
    if not parts:
        return False
    if len(parts) == 1:
        return attributes.pop(parts[0], None) is not None
    node = attributes.get(parts[0])
    if not isinstance(node, dict):
        return False
    for part in parts[1:-1]:
        children = node.get("children") or {}
        node = children.get(part)
        if not isinstance(node, dict):
            return False
    children = node.get("children") or {}
    if parts[-1] in children:
        del children[parts[-1]]
        node["children"] = children
        return True
    return False


def attribute_root(path_key: str) -> str:
    """Return the top-level attribute name for a path key."""
    head = str(path_key or "").split(".")[0]
    return head.split("{")[0]
