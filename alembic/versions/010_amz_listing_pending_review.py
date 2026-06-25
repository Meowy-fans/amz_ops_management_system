"""amz_listing_pending_review

Revision ID: 010_amz_listing_pending_review
Revises: 009_amazon_orders
Create Date: 2026-06-25
"""

from pathlib import Path

from alembic import op


revision = "010_amz_listing_pending_review"
down_revision = "009_amazon_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "amz_listing_pending_review.sql"
    )
    for statement in sql_path.read_text().split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_amz_listing_pending_review_sku")
    op.execute("DROP INDEX IF EXISTS idx_amz_listing_pending_review_status")
    op.execute("DROP TABLE IF EXISTS amz_listing_pending_review CASCADE")
