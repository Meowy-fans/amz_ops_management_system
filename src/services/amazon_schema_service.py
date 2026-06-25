"""Amazon Product Type Schema Service — cache, validate, inspect."""

import copy
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class AmazonSchemaService:
    """Product type schema cache with local validation helpers.

    DB access is delegated to AmazonProductTypeSchemaRepository.
    """

    def __init__(self, db: Session, marketplace_id: str = "ATVPDKIKX0DER"):
        self.db = db
        self.marketplace_id = marketplace_id

    @property
    def _repo(self):
        if not hasattr(self, "_repo_instance"):
            from src.repositories.amazon_product_type_schema_repository import (
                AmazonProductTypeSchemaRepository,
            )
            self._repo_instance = AmazonProductTypeSchemaRepository(self.db)
        return self._repo_instance

    # ── cache ───────────────────────────────────────────────────

    def get_cached_schema(self, product_type: str) -> Optional[Dict[str, Any]]:
        return self._repo.get(product_type, self.marketplace_id)

    def fetch_and_cache(self, product_type: str) -> Dict[str, Any]:
        from infrastructure.amazon.product_type_client import (
            AmazonProductTypeClient,
        )

        client = AmazonProductTypeClient()
        schema = client.get_schema(product_type)
        required = client.get_required_properties(product_type)
        self._repo.upsert(product_type, self.marketplace_id, schema, required)
        logger.info("Schema cached for %s (%d required props)", product_type, len(required))
        return {"schema_json": schema, "required_properties": required}

    def get_or_fetch_schema(self, product_type: str) -> Dict[str, Any]:
        cached = self.get_cached_schema(product_type)
        if cached is not None:
            return cached
        return self.fetch_and_cache(product_type)

    # ── validation ──────────────────────────────────────────────

    def get_required_properties(self, product_type: str) -> List[str]:
        data = self.get_or_fetch_schema(product_type)
        return data.get("required_properties", [])

    def get_expanded_required_properties(self, product_type: str) -> List[str]:
        """Return top-level and schema-discovered required attributes."""
        data = self.get_or_fetch_schema(product_type)
        schema = data.get("schema_json", {}) or {}
        properties = self._merged_properties(schema)

        required: List[str] = []
        self._extend_unique(required, data.get("required_properties", []) or [])
        self._collect_direct_required_property_names(schema, set(properties), required)
        return required

    def get_learned_required_properties(self, product_type: str) -> List[str]:
        """Return required attributes learned from Amazon validation feedback."""
        try:
            from src.repositories.amazon_api_submission_repository import (
                AmazonAPISubmissionRepository,
            )

            repo = AmazonAPISubmissionRepository(self.db)
            return repo.get_learned_required_attributes(product_type)
        except Exception as exc:
            logger.warning(
                "Failed to load learned required attributes for %s: %s",
                product_type,
                exc,
            )
            return []

    def get_coverage_required_properties(self, product_type: str) -> List[str]:
        """Return required attributes used by local listing coverage gates."""
        required: List[str] = []
        self._extend_unique(required, self.get_expanded_required_properties(product_type))
        self._extend_unique(required, self.get_learned_required_properties(product_type))
        return required

    def validate_attributes(
        self, product_type: str, attributes: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        required = self.get_required_properties(product_type)
        missing = []
        for prop in required:
            if prop not in attributes or not attributes[prop]:
                missing.append({
                    "property": prop,
                    "severity": "ERROR",
                    "message": f"Required property '{prop}' is missing or empty",
                })
        return missing

    # ── inspection ──────────────────────────────────────────────

    def get_valid_values(
        self, product_type: str, field_name: str
    ) -> Optional[List[str]]:
        data = self.get_or_fetch_schema(product_type)
        return self._extract_valid_values(data, field_name)

    def get_cached_valid_values(
        self, product_type: str, field_name: str
    ) -> Optional[List[str]]:
        data = self.get_cached_schema(product_type)
        if not data:
            return None
        return self._extract_valid_values(data, field_name)

    def get_property_names(self, product_type: str) -> List[str]:
        """Return top-level attribute names accepted by a product type schema."""
        data = self.get_or_fetch_schema(product_type)
        schema = data.get("schema_json", {}) or {}
        return list(self._merged_properties(schema).keys())

    def _extract_valid_values(
        self,
        data: Dict[str, Any],
        field_name: str,
    ) -> Optional[List[str]]:
        schema = data.get("schema_json", {})
        if not schema:
            return None

        props = self._merged_properties(schema)

        field_schema = props.get(field_name)
        if not field_schema:
            return None

        items = field_schema.get("items", {})
        value_schema = items.get("properties", {}).get("value", {})
        return value_schema.get("enum")

    def get_property_descriptions(self, product_type: str) -> Dict[str, str]:
        data = self.get_or_fetch_schema(product_type)
        schema = data.get("schema_json", {})
        props = dict(schema.get("properties", {}))
        for part in schema.get("allOf", []):
            props.update(part.get("properties", {}))

        descs: Dict[str, str] = {}
        for name, prop in props.items():
            desc = prop.get("description") or prop.get("title", "")
            if desc:
                descs[name] = desc
        return descs

    @classmethod
    def _merged_properties(cls, schema: Dict[str, Any]) -> Dict[str, Any]:
        props = copy.deepcopy(schema.get("properties", {}) or {})
        for part in schema.get("allOf", []) or []:
            cls._merge_property_layer(props, part.get("properties", {}) or {})
            for key in ("then", "else"):
                cls._merge_property_layer(
                    props,
                    (part.get(key) or {}).get("properties", {}) or {},
                )
        return props

    @classmethod
    def _merge_property_layer(
        cls,
        props: Dict[str, Any],
        layer: Dict[str, Any],
    ) -> None:
        for name, definition in (layer or {}).items():
            if (
                name in props
                and isinstance(props[name], dict)
                and isinstance(definition, dict)
            ):
                props[name] = cls._deep_merge_schema_node(props[name], definition)
            else:
                props[name] = copy.deepcopy(definition)

    @classmethod
    def _deep_merge_schema_node(cls, base: Any, overlay: Any) -> Any:
        if not isinstance(base, dict) or not isinstance(overlay, dict):
            return copy.deepcopy(overlay)

        merged = copy.deepcopy(base)
        for key, value in overlay.items():
            if key not in merged:
                merged[key] = copy.deepcopy(value)
                continue
            if key == "required" and isinstance(merged[key], list) and isinstance(value, list):
                merged[key] = list(dict.fromkeys([*merged[key], *value]))
                continue
            if isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = cls._deep_merge_schema_node(merged[key], value)
                continue
            if isinstance(merged[key], dict) and not isinstance(value, dict):
                continue
            merged[key] = copy.deepcopy(value)
        return merged

    @classmethod
    def _collect_direct_required_property_names(
        cls,
        schema: Dict[str, Any],
        property_names: set[str],
        required: List[str],
    ) -> None:
        for name in schema.get("required", []) or []:
            if name in property_names:
                cls._append_unique(required, name)
        for part in schema.get("allOf", []) or []:
            for name in part.get("required", []) or []:
                if name in property_names:
                    cls._append_unique(required, name)

    @classmethod
    def _contains_nested_required(cls, node: Any) -> bool:
        generic_required = {"value", "unit", "currency", "language_tag", "marketplace_id"}
        if isinstance(node, dict):
            required = {
                str(name)
                for name in (node.get("required", []) or [])
                if str(name) not in generic_required
            }
            if required:
                return True
            return any(cls._contains_nested_required(value) for value in node.values())
        if isinstance(node, list):
            return any(cls._contains_nested_required(item) for item in node)
        return False

    @staticmethod
    def _append_unique(items: List[str], value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in items:
            items.append(text)

    @classmethod
    def _extend_unique(cls, items: List[str], values: List[Any]) -> None:
        for value in values:
            cls._append_unique(items, value)
