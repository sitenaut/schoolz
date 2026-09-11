"""community_submissions - the Contact Us / community-contributed content inbox

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-11 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "community_submissions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_content_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("submitter_name", sa.String(length=200), nullable=True),
        sa.Column("submitter_email", sa.String(length=255), nullable=True),
        sa.Column("school_id", sa.String(length=36), sa.ForeignKey("schools.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "district_id", sa.String(length=36), sa.ForeignKey("districts.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("admin_notes", sa.String(length=2000), nullable=True),
        sa.Column(
            "reviewed_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_community_submissions_status", "community_submissions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_community_submissions_status", table_name="community_submissions")
    op.drop_table("community_submissions")
