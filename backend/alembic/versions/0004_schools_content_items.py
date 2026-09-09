"""schools, school content items, newsletter->school link

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schools",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("main_phone", sa.String(length=50), nullable=True),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("absence_method", sa.String(length=20), nullable=True),
        sa.Column("absence_emails", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("absence_phone", sa.String(length=50), nullable=True),
        sa.Column("absence_instructions", sa.String(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("smore_newsletters", sa.Column("school_id", sa.String(length=36), sa.ForeignKey("schools.id", ondelete="SET NULL"), nullable=True))
    op.add_column("smore_newsletters", sa.Column("latest_summary", sa.String(), nullable=True))

    op.create_table(
        "school_content_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("school_id", sa.String(length=36), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("newsletter_id", sa.String(length=36), sa.ForeignKey("smore_newsletters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_block_id", sa.String(length=36), sa.ForeignKey("smore_blocks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_all_day", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("link_url", sa.String(length=1000), nullable=True),
        sa.Column("person_name", sa.String(length=200), nullable=True),
        sa.Column("person_title", sa.String(length=200), nullable=True),
        sa.Column("source_excerpt", sa.String(length=1000), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_school_content_items_school_id", "school_content_items", ["school_id"])
    op.create_index("ix_school_content_items_category", "school_content_items", ["category"])
    op.create_foreign_key(
        "fk_school_content_items_superseded_by",
        "school_content_items",
        "school_content_items",
        ["superseded_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_table("school_content_items")
    op.drop_column("smore_newsletters", "latest_summary")
    op.drop_column("smore_newsletters", "school_id")
    op.drop_table("schools")
