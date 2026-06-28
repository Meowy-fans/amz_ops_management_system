"""amz_listing_pending_rule_review

Revision ID: 013_amz_listing_pending_rule_review
Revises: 012_amz_listing_learned_required_paths_v2
Create Date: 2026-06-28
"""

from pathlib import Path

from alembic import op


revision = "013_amz_listing_pending_rule_review"
down_revision = "012_amz_listing_learned_required_paths_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "amz_listing_pending_rule_review.sql"
    )
    for statement in sql_path.read_text().split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_amz_listing_pending_rule_review_category")
    op.execute("DROP TABLE IF EXISTS amz_listing_pending_rule_review CASCADE")
