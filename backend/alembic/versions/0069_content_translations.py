"""content_translations - cached machine translations of school content items.

Revision ID: 0069
Revises: 0068
Create Date: 2026-09-29 14:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0069"
down_revision: Union[str, None] = "0068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_translations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("item_id", sa.String(36), sa.ForeignKey("school_content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lang", sa.String(8), nullable=False),
        sa.Column("title", sa.String(600), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "lang", name="uq_content_translations_item_lang"),
    )
    # RLS on with no policies, like every other table: nothing goes through
    # Supabase's Data API.
    op.execute("ALTER TABLE content_translations ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("content_translations")
