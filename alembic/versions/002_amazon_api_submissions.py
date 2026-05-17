"""amazon_api_submissions

Revision ID: 002_amazon_api_submissions
Revises: 001_initial_schema
Create Date: 2026-05-17 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import os


# revision identifiers, used by Alembic.
revision: str = '002_amazon_api_submissions'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    file_path = os.path.join(os.path.dirname(__file__), '../../migrations', 'amazon_api_submissions.sql')
    with open(file_path, 'r') as f:
        sql = f.read()
    for statement in sql.split(';'):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_amazon_api_submissions_submitted")
    op.execute("DROP INDEX IF EXISTS idx_amazon_api_submissions_status")
    op.execute("DROP INDEX IF EXISTS idx_amazon_api_submissions_sku")
    op.execute("DROP TABLE IF EXISTS amazon_api_submissions CASCADE")
