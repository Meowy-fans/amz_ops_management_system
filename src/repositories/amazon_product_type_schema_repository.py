"""Repository for amazon_product_type_schemas cache table."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class AmazonProductTypeSchemaRepository:
    """Data access for cached Amazon Product Type Definitions schemas."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, product_type: str, marketplace_id: str) -> Optional[Dict[str, Any]]:
        row = self.db.execute(
            text(
                """
                SELECT schema_json, required_properties, retrieved_at
                FROM amazon_product_type_schemas
                WHERE product_type = :pt AND marketplace_id = :mid
                """
            ),
            {"pt": product_type, "mid": marketplace_id},
        ).fetchone()
        if row is None:
            return None
        return {
            "schema_json": row[0],
            "required_properties": row[1],
            "retrieved_at": row[2],
        }

    def upsert(
        self,
        product_type: str,
        marketplace_id: str,
        schema: Dict[str, Any],
        required_properties: list,
    ) -> None:
        self.db.execute(
            text(
                """
                INSERT INTO amazon_product_type_schemas
                    (product_type, marketplace_id, schema_json,
                     required_properties, retrieved_at)
                VALUES (:pt, :mid, :schema, :req, :ts)
                ON CONFLICT (product_type, marketplace_id) DO UPDATE SET
                    schema_json = EXCLUDED.schema_json,
                    required_properties = EXCLUDED.required_properties,
                    retrieved_at = EXCLUDED.retrieved_at
                """
            ),
            {
                "pt": product_type,
                "mid": marketplace_id,
                "schema": json.dumps(schema),
                "req": json.dumps(required_properties),
                "ts": datetime.now(timezone.utc),
            },
        )
        self.db.commit()
