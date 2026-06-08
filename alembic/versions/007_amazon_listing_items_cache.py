"""amazon_listing_items_cache

Revision ID: 007_amazon_listing_items_cache
Revises: 006_variation_resolution_runs
Create Date: 2026-06-08 10:00:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op


revision: str = "007_amazon_listing_items_cache"
down_revision: Union[str, None] = "006_variation_resolution_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    file_path = os.path.join(
        os.path.dirname(__file__),
        "../../migrations",
        "amazon_listing_items_cache.sql",
    )
    with open(file_path, "r") as f:
        sql = f.read()
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_amazon_listing_items_cache_last_seen")
    op.execute("DROP INDEX IF EXISTS idx_amazon_listing_items_cache_product_type")
    op.execute("DROP TABLE IF EXISTS amazon_listing_items_cache CASCADE")
