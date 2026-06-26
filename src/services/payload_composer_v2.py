"""Generic payload composer for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

from typing import Any, Dict

from src.services.requirement_models_v2 import RequirementNode, ResolutionNode


class PayloadComposerV2:
    """Render requirement/resolution trees into Listings Items API attributes."""

    def compose(
        self,
        requirement_root: RequirementNode,
        resolution_root: ResolutionNode,
    ) -> Dict[str, Any]:
        """Return Amazon Listings Items API attributes for resolved nodes."""
        resolution_index = self._index_resolutions(resolution_root)
        attributes: Dict[str, Any] = {}
        for requirement in requirement_root.children:
            resolution = resolution_index.get(requirement.path_key)
            rendered = self._render_top_level(requirement, resolution, resolution_index)
            if rendered is not None:
                attributes[requirement.name] = rendered
        return attributes

    def _render_top_level(
        self,
        requirement: RequirementNode,
        resolution: ResolutionNode | None,
        resolution_index: Dict[str, ResolutionNode],
    ) -> Any:
        value = self._render_node(requirement, resolution, resolution_index)
        if value is None:
            return None
        if requirement.shape in {"list_value", "measure", "object", "nested_object", "array_object"}:
            return value if isinstance(value, list) else [value]
        return [{"value": value}]

    def _render_node(
        self,
        requirement: RequirementNode,
        resolution: ResolutionNode | None,
        resolution_index: Dict[str, ResolutionNode],
    ) -> Any:
        if resolution and resolution.blocking:
            return None
        if requirement.shape == "list_value":
            return self._render_list_value(requirement, resolution)
        if requirement.shape == "measure":
            return self._render_measure(requirement, resolution, resolution_index)
        if requirement.shape in {"object", "nested_object", "array_object"}:
            return self._render_object(requirement, resolution, resolution_index)
        return self._scalar_value(resolution.value if resolution else None)

    def _render_list_value(
        self,
        requirement: RequirementNode,
        resolution: ResolutionNode | None,
    ) -> list[Dict[str, Any]] | None:
        raw = resolution.value if resolution else None
        if raw in (None, "", []):
            return None
        values = raw if isinstance(raw, list) else [raw]
        rendered = []
        for value in values:
            scalar = self._scalar_value(value)
            if scalar in (None, ""):
                continue
            item = dict(requirement.auto_fields)
            item["value"] = scalar
            rendered.append(item)
        return rendered or None

    def _render_measure(
        self,
        requirement: RequirementNode,
        resolution: ResolutionNode | None,
        resolution_index: Dict[str, ResolutionNode],
    ) -> Dict[str, Any] | None:
        item = dict(requirement.auto_fields)
        if resolution and isinstance(resolution.value, dict):
            for key in ("value", "unit"):
                if resolution.value.get(key) not in (None, "", []):
                    item[key] = resolution.value[key]
        for child in requirement.children:
            child_resolution = resolution_index.get(child.path_key)
            if child_resolution and not child_resolution.blocking:
                value = self._scalar_value(child_resolution.value)
                if value not in (None, ""):
                    item[child.name] = value
        return item if self._has_non_auto_value(item, requirement) else None

    def _render_object(
        self,
        requirement: RequirementNode,
        resolution: ResolutionNode | None,
        resolution_index: Dict[str, ResolutionNode],
    ) -> Dict[str, Any] | list[Dict[str, Any]] | None:
        if resolution and isinstance(resolution.value, list):
            rendered_items = [
                item
                for value in resolution.value
                if isinstance(value, dict)
                for item in [self._merge_object_value(requirement, value)]
                if self._has_non_auto_value(item, requirement)
            ]
            return rendered_items or None

        item = dict(requirement.auto_fields)
        if resolution and isinstance(resolution.value, dict):
            item.update(
                {
                    key: value
                    for key, value in resolution.value.items()
                    if value not in (None, "", [])
                }
            )
        for child in requirement.children:
            child_resolution = resolution_index.get(child.path_key)
            child_value = self._render_node(child, child_resolution, resolution_index)
            if child_value is not None:
                item[child.name] = child_value
        return item if self._has_non_auto_value(item, requirement) else None

    @staticmethod
    def _merge_object_value(
        requirement: RequirementNode,
        value: Dict[str, Any],
    ) -> Dict[str, Any]:
        item = dict(requirement.auto_fields)
        item.update({key: item_value for key, item_value in value.items() if item_value not in (None, "", [])})
        return item

    @staticmethod
    def _scalar_value(value: Any) -> Any:
        if isinstance(value, dict):
            if "value" in value:
                return value.get("value")
            if "name" in value:
                return value.get("name")
        return value

    @staticmethod
    def _index_resolutions(root: ResolutionNode) -> Dict[str, ResolutionNode]:
        index: Dict[str, ResolutionNode] = {}

        def visit(node: ResolutionNode) -> None:
            index[node.path_key] = node
            for child in node.children:
                visit(child)

        visit(root)
        return index

    @staticmethod
    def _has_non_auto_value(item: Dict[str, Any], requirement: RequirementNode) -> bool:
        return any(
            value not in (None, "", [])
            for key, value in item.items()
            if key not in requirement.auto_fields
        )
