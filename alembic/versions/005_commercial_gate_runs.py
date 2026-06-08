"""commercial_gate_runs

Revision ID: 005_commercial_gate_runs
Revises: 004_product_image_assets
Create Date: 2026-06-08 08:20:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op


revision: str = "005_commercial_gate_runs"
down_revision: Union[str, None] = "004_product_image_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    file_path = os.path.join(
        os.path.dirname(__file__),
        "../../migrations",
        "amazon_listing_commercial_gate_runs.sql",
    )
    with open(file_path, "r") as f:
        sql = f.read()
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_commercial_gate_runs_decision")
    op.execute("DROP INDEX IF EXISTS idx_commercial_gate_runs_sku_created")
    op.execute("DROP TABLE IF EXISTS amazon_listing_commercial_gate_runs CASCADE")
