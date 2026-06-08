"""giga_product_base_prices_unique_sku

Revision ID: 008_giga_base_price_sku_unique
Revises: 007_amazon_listing_items_cache
Create Date: 2026-06-08
"""

from pathlib import Path

from alembic import op


revision = "008_giga_base_price_sku_unique"
down_revision = "007_amazon_listing_items_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "giga_product_base_prices_unique_sku.sql"
    )
    op.execute(sql_path.read_text())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uniq_giga_product_base_prices_sku")
