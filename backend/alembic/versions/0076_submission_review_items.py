"""draft calendar items for reviewing community submissions

Revision ID: 0076
Revises: 0075
Create Date: 2026-10-05 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0076"
down_revision: Union[str, None] = "0075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("community_submissions", sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "community_submission_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "submission_id",
            sa.String(length=36),
            sa.ForeignKey("community_submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origin", sa.String(length=10), nullable=False, server_default="manual"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("category", sa.String(length=30), nullable=False, server_default="event"),
        sa.Column("scope", sa.String(length=10), nullable=False, server_default="school"),
        sa.Column("start_local", sa.String(length=19), nullable=True),
        sa.Column("end_local", sa.String(length=19), nullable=True),
        sa.Column("stated_weekday", sa.String(length=10), nullable=True),
        sa.Column("tentative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reader_note", sa.String(length=1000), nullable=True),
        sa.Column("source_excerpt", sa.String(length=1000), nullable=True),
        sa.Column(
            "replaces_item_id",
            sa.String(length=36),
            sa.ForeignKey("school_content_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "content_item_id",
            sa.String(length=36),
            sa.ForeignKey("school_content_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_community_submission_items_submission_id", "community_submission_items", ["submission_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_community_submission_items_submission_id", table_name="community_submission_items")
    op.drop_table("community_submission_items")
    op.drop_column("community_submissions", "extracted_at")
