"""add bucket3 grade tables: child_course_grades, child_grade_entries

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-14 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "child_course_grades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_code", sa.String(20), nullable=False),
        sa.Column("course_section", sa.String(10), nullable=False),
        sa.Column("course_name", sa.String(255), nullable=True),
        sa.Column("marking_period", sa.String(10), nullable=False),
        sa.Column("grade_percent", sa.Float(), nullable=True),
        sa.Column("last_grade_posted", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "course_code", "course_section", "marking_period", name="uq_child_course_grade"),
    )
    op.create_index("ix_child_course_grades_student_id", "child_course_grades", ["student_id"])

    op.create_table(
        "child_grade_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_uid", sa.String(255), nullable=False),
        sa.Column("course_code", sa.String(20), nullable=False),
        sa.Column("course_section", sa.String(10), nullable=False),
        sa.Column("course_name", sa.String(255), nullable=True),
        sa.Column("marking_period", sa.String(10), nullable=True),
        sa.Column("weekday_date", sa.String(20), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("score_earned", sa.Float(), nullable=True),
        sa.Column("score_possible", sa.Float(), nullable=True),
        sa.Column("percent", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("is_updated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "external_uid", name="uq_child_grade_entry"),
    )
    op.create_index("ix_child_grade_entries_student_id", "child_grade_entries", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_child_grade_entries_student_id", table_name="child_grade_entries")
    op.drop_table("child_grade_entries")
    op.drop_index("ix_child_course_grades_student_id", table_name="child_course_grades")
    op.drop_table("child_course_grades")
