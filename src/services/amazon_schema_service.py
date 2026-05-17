"""Amazon Product Type Schema Service — cache, validate, inspect."""

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
        schema = data.get("schema_json", {})
        if not schema:
            return None

        props = dict(schema.get("properties", {}))
        for part in schema.get("allOf", []):
            props.update(part.get("properties", {}))

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
