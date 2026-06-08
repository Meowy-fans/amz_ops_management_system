"""variation_resolution_runs

Revision ID: 006_variation_resolution_runs
Revises: 005_commercial_gate_runs
Create Date: 2026-06-08 09:00:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op


revision: str = "006_variation_resolution_runs"
down_revision: Union[str, None] = "005_commercial_gate_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    file_path = os.path.join(
        os.path.dirname(__file__),
        "../../migrations",
        "amazon_variation_resolution_runs.sql",
    )
    with open(file_path, "r") as f:
        sql = f.read()
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_variation_resolution_runs_decision")
    op.execute("DROP INDEX IF EXISTS idx_variation_resolution_runs_parent")
    op.execute("DROP TABLE IF EXISTS amazon_variation_resolution_runs CASCADE")
