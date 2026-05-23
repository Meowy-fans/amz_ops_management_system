"""amazon_listing_issues

Revision ID: 003_amazon_listing_issues
Revises: 002_amazon_api_submissions
Create Date: 2026-05-23 00:00:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "003_amazon_listing_issues"
down_revision: Union[str, None] = "002_amazon_api_submissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    file_path = os.path.join(
        os.path.dirname(__file__),
        "../../migrations",
        "amazon_listing_issues.sql",
    )
    with open(file_path, "r") as f:
        sql = f.read()
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_amazon_listing_issue_actions_issue")
    op.execute("DROP INDEX IF EXISTS idx_amazon_listing_issue_actions_status")
    op.execute("DROP TABLE IF EXISTS amazon_listing_issue_actions CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_amazon_listing_issues_last_seen")
    op.execute("DROP INDEX IF EXISTS idx_amazon_listing_issues_sku")
    op.execute("DROP INDEX IF EXISTS idx_amazon_listing_issues_status")
    op.execute("DROP TABLE IF EXISTS amazon_listing_issues CASCADE")
    op.execute("DROP TABLE IF EXISTS amazon_listing_issue_scan_runs CASCADE")
