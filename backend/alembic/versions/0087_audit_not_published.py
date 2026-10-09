"""audit_not_published - the data audit's "Mark as not published"

One row per (school, data point) a school confirmed it doesn't publish - see
models.AuditNotPublished.

Revision ID: 0086
Revises: 0085
Create Date: 2026-10-09 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0086"
down_revision: Union[str, None] = "0085"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_not_published",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("school_id", sa.String(length=36), nullable=False),
        sa.Column("data_point", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "data_point", name="uq_audit_not_published_school_point"),
    )
    op.create_index("ix_audit_not_published_school_id", "audit_not_published", ["school_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_not_published_school_id", table_name="audit_not_published")
    op.drop_table("audit_not_published")
