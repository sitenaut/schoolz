"""kids view v2: work item enrichment, completion tracking, shared suggestions

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-15 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("child_work_items", sa.Column("teacher_name", sa.String(200), nullable=True))
    op.add_column("child_work_items", sa.Column("posted_raw", sa.String(100), nullable=True))
    op.add_column("child_work_items", sa.Column("posted_date", sa.String(10), nullable=True))
    op.add_column("child_work_items", sa.Column("body", sa.String(), nullable=True))

    op.create_table(
        "child_work_item_progress",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "work_item_id", sa.String(36), sa.ForeignKey("child_work_items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("done", sa.Boolean(), nullable=False),
        sa.Column("marked_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "work_item_id", name="uq_child_work_item_progress"),
    )
    op.create_index("ix_child_work_item_progress_student_id", "child_work_item_progress", ["student_id"])

    op.create_table(
        "assignment_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_code", sa.String(120), nullable=False),
        sa.Column("course_section", sa.String(20), nullable=False),
        sa.Column("normalized_title", sa.String(500), nullable=False),
        sa.Column("suggestion_text", sa.String(), nullable=True),
        sa.Column("declined", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("course_code", "course_section", "normalized_title", name="uq_assignment_suggestion"),
    )


def downgrade() -> None:
    op.drop_table("assignment_suggestions")
    op.drop_index("ix_child_work_item_progress_student_id", table_name="child_work_item_progress")
    op.drop_table("child_work_item_progress")
    op.drop_column("child_work_items", "body")
    op.drop_column("child_work_items", "posted_date")
    op.drop_column("child_work_items", "posted_raw")
    op.drop_column("child_work_items", "teacher_name")
