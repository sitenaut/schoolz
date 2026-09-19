"""per-course late-work policies, and a record of asking a teacher for help

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-19 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "course_late_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_code", sa.String(120), nullable=False),
        sa.Column("course_section", sa.String(20), nullable=False),
        sa.Column("course_name", sa.String(255), nullable=True),
        sa.Column("shape", sa.String(20), nullable=False),
        sa.Column("penalty_pct", sa.Float(), nullable=True),
        sa.Column("penalty_per_day", sa.Float(), nullable=True),
        sa.Column("floor_pct", sa.Float(), nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("accepted_until", sa.String(30), nullable=True),
        sa.Column("applies_to_types", sa.JSON(), nullable=True),
        sa.Column("extension_by_request", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_text", sa.String(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "course_code", "course_section", name="uq_course_late_policy"),
    )

    op.create_table(
        "help_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "work_item_id", sa.String(36), sa.ForeignKey("child_work_items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("teacher_email", sa.String(255), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_help_requests_student_id", "help_requests", ["student_id"])
    op.create_index("ix_help_requests_work_item_id", "help_requests", ["work_item_id"])


def downgrade() -> None:
    op.drop_index("ix_help_requests_work_item_id", table_name="help_requests")
    op.drop_index("ix_help_requests_student_id", table_name="help_requests")
    op.drop_table("help_requests")
    op.drop_table("course_late_policies")
