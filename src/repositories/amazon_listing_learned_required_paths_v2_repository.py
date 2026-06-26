"""Repository for V2 learned required paths from Amazon feedback."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class AmazonListingLearnedRequiredPathsV2Repository:
    """Persists Amazon-learned required path_keys per category."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_learned(
        self,
        category: str,
        path_key: str,
        path_key_version: str,
        attribute: str,
        source_submission_id: Optional[int],
    ) -> int:
        query = text("""
            INSERT INTO amz_listing_learned_required_paths_v2 (
                category, path_key, path_key_version, attribute,
                source_submission_id, sample_count
            ) VALUES (
                :category, :path_key, :path_key_version, :attribute,
                :source_submission_id, 1
            )
            ON CONFLICT (category, path_key, path_key_version) DO UPDATE SET
                attribute = EXCLUDED.attribute,
                source_submission_id = EXCLUDED.source_submission_id,
                sample_count = amz_listing_learned_required_paths_v2.sample_count + 1,
                last_seen_at = NOW()
            RETURNING id
        """)
        result = self.db.execute(
            query,
            {
                "category": category,
                "path_key": path_key,
                "path_key_version": path_key_version,
                "attribute": attribute,
                "source_submission_id": source_submission_id,
            },
        )
        self.db.commit()
        return int(result.scalar_one())

    def list_for_category(self, category: str) -> List[str]:
        query = text("""
            SELECT path_key
            FROM amz_listing_learned_required_paths_v2
            WHERE category = :category
            ORDER BY path_key ASC
        """)
        rows = self.db.execute(query, {"category": category}).mappings()
        return [str(row["path_key"]) for row in rows]

    def list_for_category_and_paths(
        self,
        category: str,
        path_keys: List[str],
    ) -> List[str]:
        if not path_keys:
            return []
        query = text("""
            SELECT path_key
            FROM amz_listing_learned_required_paths_v2
            WHERE category = :category
              AND path_key = ANY(:path_keys)
            ORDER BY path_key ASC
        """)
        rows = self.db.execute(
            query,
            {"category": category, "path_keys": list(path_keys)},
        ).mappings()
        return [str(row["path_key"]) for row in rows]
