"""add bucket3 tables: captures, schedule blocks, day cycles, work items, page kinds

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-14 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bucket3_captures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("adapter", sa.String(20), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("reduced_text", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "source_url", "content_hash", name="uq_bucket3_capture_dedup"),
    )
    op.create_index("ix_bucket3_captures_student_id", "bucket3_captures", ["student_id"])

    op.create_table(
        "child_schedule_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("schedule_date", sa.String(10), nullable=True),
        sa.Column("course_name", sa.String(255), nullable=False),
        sa.Column("teacher", sa.String(255), nullable=True),
        sa.Column("room", sa.String(50), nullable=True),
        sa.Column("term", sa.String(20), nullable=True),
        sa.Column("days", sa.String(20), nullable=True),
        sa.Column("time_start", sa.String(20), nullable=True),
        sa.Column("time_end", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "source", "period", "schedule_date", "term", name="uq_child_schedule_block"),
    )
    op.create_index("ix_child_schedule_blocks_student_id", "child_schedule_blocks", ["student_id"])

    op.create_table(
        "child_day_cycles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_date", sa.String(10), nullable=False),
        sa.Column("cycle_label", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "schedule_date", name="uq_child_day_cycle"),
    )

    op.create_table(
        "child_work_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_uid", sa.String(255), nullable=False),
        sa.Column("course_name", sa.String(255), nullable=True),
        sa.Column("course_external_id", sa.String(100), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("due_raw", sa.String(100), nullable=True),
        sa.Column("due_date", sa.String(10), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "external_uid", name="uq_child_work_item"),
    )
    op.create_index("ix_child_work_items_student_id", "child_work_items", ["student_id"])

    op.create_table(
        "capture_page_kinds",
        sa.Column("pattern", sa.String(100), primary_key=True),
        sa.Column("adapter", sa.String(20), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("example_url", sa.String(1000), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("capture_page_kinds")
    op.drop_index("ix_child_work_items_student_id", table_name="child_work_items")
    op.drop_table("child_work_items")
    op.drop_table("child_day_cycles")
    op.drop_index("ix_child_schedule_blocks_student_id", table_name="child_schedule_blocks")
    op.drop_table("child_schedule_blocks")
    op.drop_index("ix_bucket3_captures_student_id", table_name="bucket3_captures")
    op.drop_table("bucket3_captures")
