"""staff roster

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("school_id", sa.String(length=36), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_constituent_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("department", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("school_id", "source_constituent_id", name="uq_staff_member_school_constituent"),
    )
    op.create_index("ix_staff_members_school_id", "staff_members", ["school_id"])

    op.add_column("schools", sa.Column("staff_roster_job_id", sa.String(length=36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True))
    op.add_column(
        "school_content_items",
        sa.Column("staff_member_id", sa.String(length=36), sa.ForeignKey("staff_members.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("school_content_items", "staff_member_id")
    op.drop_column("schools", "staff_roster_job_id")
    op.drop_table("staff_members")
