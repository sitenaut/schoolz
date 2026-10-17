"""resource_eligibility: structured "who can come" criteria, one row per distinct eligibility sentence

Revision ID: 0104
Revises: 0103
Create Date: 2026-10-16 21:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0104"
down_revision: str | None = "0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_eligibility",
        sa.Column("text_key", sa.String(64), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("criteria", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("ALTER TABLE resource_eligibility ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("resource_eligibility")
