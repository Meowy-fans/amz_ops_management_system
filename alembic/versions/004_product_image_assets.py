"""product_image_assets

Revision ID: 004_product_image_assets
Revises: 003_amazon_listing_issues
Create Date: 2026-06-08 04:50:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op


revision: str = "004_product_image_assets"
down_revision: Union[str, None] = "003_amazon_listing_issues"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    file_path = os.path.join(
        os.path.dirname(__file__),
        "../../migrations",
        "product_image_assets.sql",
    )
    with open(file_path, "r") as f:
        sql = f.read()
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_product_image_assets_checksum")
    op.execute("DROP INDEX IF EXISTS idx_product_image_assets_vendor_sku")
    op.execute("DROP INDEX IF EXISTS idx_product_image_assets_sku_status")
    op.execute("DROP TABLE IF EXISTS product_image_assets CASCADE")
