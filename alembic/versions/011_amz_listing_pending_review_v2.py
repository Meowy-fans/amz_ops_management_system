"""amz_listing_pending_review_v2

Revision ID: 011_amz_listing_pending_review_v2
Revises: 010_amz_listing_pending_review
Create Date: 2026-06-26
"""

from pathlib import Path

from alembic import op


revision = "011_amz_listing_pending_review_v2"
down_revision = "010_amz_listing_pending_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "amz_listing_pending_review_v2.sql"
    )
    for statement in sql_path.read_text().split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_amz_listing_pending_review_v2_sku")
    op.execute("DROP INDEX IF EXISTS idx_amz_listing_pending_review_v2_status")
    op.execute("DROP INDEX IF EXISTS idx_amz_listing_pending_review_v2_path")
    op.execute("DROP TABLE IF EXISTS amz_listing_pending_review_v2 CASCADE")
