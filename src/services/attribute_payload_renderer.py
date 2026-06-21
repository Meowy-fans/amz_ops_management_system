"""Render AttributeResolution objects to Listings Items API shapes."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from src.services.attribute_resolver import AttributeResolution


class AttributePayloadRenderer:
    """Converts resolved attributes into SP-API attribute JSON."""

    def render(
        self,
        resolutions: Dict[str, AttributeResolution],
        allowed_attributes: Iterable[str] | None = None,
    ) -> Dict[str, Any]:
        attrs: Dict[str, Any] = {}
        allowed = self._allowed_set(allowed_attributes)
        for name, resolution in resolutions.items():
            if allowed is not None and name not in allowed:
                continue
            if resolution.blocking or resolution.value in (None, ""):
                continue
            if resolution.shape == "list_value":
                values = resolution.value
                if not isinstance(values, list):
                    values = [values]
                attrs[name] = [{"value": value} for value in values if value not in (None, "")]
            elif resolution.shape == "measure":
                value = self._render_measure(resolution.value)
                if value:
                    attrs[name] = [value]
            elif resolution.shape in {"object", "nested_object"}:
                values = resolution.value
                if not isinstance(values, list):
                    values = [values]
                attrs[name] = [
                    value for value in values
                    if isinstance(value, dict) and value
                ]
            else:
                attrs[name] = [{"value": resolution.value}]
        return attrs

    @classmethod
    def filter_allowed_attributes(
        cls,
        attrs: Dict[str, Any],
        allowed_attributes: Iterable[str] | None,
    ) -> Dict[str, Any]:
        """Drop attributes not present in the product type schema allowlist."""
        allowed = cls._allowed_set(allowed_attributes)
        if allowed is None:
            return attrs
        return {name: value for name, value in attrs.items() if name in allowed}

    @staticmethod
    def _allowed_set(allowed_attributes: Iterable[str] | None) -> set[str] | None:
        if allowed_attributes is None:
            return None
        allowed = {str(name) for name in allowed_attributes if str(name or "").strip()}
        return allowed or None

    @staticmethod
    def _render_measure(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {"value": value} if value not in (None, "") else {}
        rendered = {
            key: item
            for key, item in value.items()
            if item not in (None, "", [])
        }
        return rendered
