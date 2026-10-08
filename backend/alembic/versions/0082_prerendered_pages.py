"""prerendered_pages - crawler HTML snapshots shared across API machines

Replaces services/prerender.py's process-local cache, which every deploy and
auto-stop wiped and which each API machine kept separately.

Revision ID: 0082
Revises: 0081
Create Date: 2026-10-08 13:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0082"
down_revision: Union[str, None] = "0081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prerendered_pages",
        sa.Column("path", sa.String(length=200), primary_key=True),
        sa.Column("html_gz", sa.LargeBinary(), nullable=False),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("ALTER TABLE prerendered_pages ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("prerendered_pages")
