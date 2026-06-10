"""amazon_orders

Revision ID: 009_amazon_orders
Revises: 008_giga_base_price_sku_unique
Create Date: 2026-06-10
"""

from pathlib import Path

from alembic import op


revision = "009_amazon_orders"
down_revision = "008_giga_base_price_sku_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[2] / "migrations" / "amazon_orders.sql"
    for statement in sql_path.read_text().split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_amazon_order_items_seller_sku")
    op.execute("DROP TABLE IF EXISTS amazon_order_items CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_amazon_orders_last_seen")
    op.execute("DROP INDEX IF EXISTS idx_amazon_orders_notified")
    op.execute("DROP INDEX IF EXISTS idx_amazon_orders_status")
    op.execute("DROP TABLE IF EXISTS amazon_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS amazon_order_sync_runs CASCADE")
