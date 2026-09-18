"""add child_marking_periods

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-14 17:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "child_marking_periods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(10), nullable=False),
        sa.Column("start_date", sa.String(10), nullable=False),
        sa.Column("end_date", sa.String(10), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "label", name="uq_child_marking_period"),
    )
    op.create_index("ix_child_marking_periods_student_id", "child_marking_periods", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_child_marking_periods_student_id", table_name="child_marking_periods")
    op.drop_table("child_marking_periods")
