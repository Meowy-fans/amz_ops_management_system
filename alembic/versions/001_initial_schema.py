"""initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-02-23 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import os

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def read_sql_file(filename):
    file_path = os.path.join(os.path.dirname(__file__), '../../migrations', filename)
    with open(file_path, 'r') as f:
        # Filter out psql-specific commands and host-specific ownership changes.
        raw_lines = f.readlines()

    lines = []
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        next_line = raw_lines[index + 1] if index + 1 < len(raw_lines) else ''
        if line.strip().startswith('\\'):
            index += 1
            continue
        if (
            line.strip().lower().startswith('alter table ')
            and 'owner to mars_user' in next_line.lower()
        ):
            index += 2
            continue
        if 'owner to mars_user' in line.lower():
            index += 1
            continue
        lines.append(line)
        index += 1

    return "".join(lines)

def upgrade() -> None:
    # Execute SQL files in order
    # 1. Base initialization
    op.execute(read_sql_file('init_db.sql'))
    
    # 2. Giga tables (meow_sku_map, giga_product_sync_records, etc.)
    op.execute(read_sql_file('create_giga_tables.sql'))
    
    # 3. Giga Price tables (giga_product_base_prices)
    # Check if file exists first just in case
    if os.path.exists(os.path.join(os.path.dirname(__file__), '../../migrations/create_giga_price_tables.sql')):
        op.execute(read_sql_file('create_giga_price_tables.sql'))
        
    # 4. Listing Log tables
    op.execute(read_sql_file('create_listing_log_table.sql'))

    # 5. LLM-generated product detail table
    op.execute(read_sql_file('create_ds_api_product_details.sql'))

    # 6. Final pricing table and baseline supplier category mappings
    op.execute("""
        ALTER TABLE supplier_categories_map
        ADD COLUMN IF NOT EXISTS supplier_category_name VARCHAR(255) NOT NULL DEFAULT ''
    """)
    op.execute(read_sql_file('setup_pricing_system.sql'))

    # 7. Amazon template rules and seed data
    op.execute(read_sql_file('amazon_cat_templates.sql'))
    op.execute("""
        SELECT setval(
            pg_get_serial_sequence('amazon_cat_templates', 'id'),
            COALESCE((SELECT MAX(id) FROM amazon_cat_templates), 1),
            true
        )
    """)


def downgrade() -> None:
    # Drop tables in reverse order of dependency
    op.execute("DROP TABLE IF EXISTS amz_listing_log CASCADE")
    op.execute("DROP TABLE IF EXISTS amazon_cat_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS ds_api_product_details CASCADE")
    op.execute("DROP TABLE IF EXISTS product_final_prices CASCADE")
    op.execute("DROP TABLE IF EXISTS giga_product_base_prices CASCADE")
    op.execute("DROP TABLE IF EXISTS supplier_categories_map CASCADE")
    op.execute("DROP TABLE IF EXISTS product_base_prices CASCADE")
    op.execute("DROP TABLE IF EXISTS meow_sku_map CASCADE")
    op.execute("DROP TABLE IF EXISTS giga_product_sync_records CASCADE")
    op.execute("DROP TABLE IF EXISTS amz_all_listing_report CASCADE")
