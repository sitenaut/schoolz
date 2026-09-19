"""per-assignment late exceptions ("I'll take it by the 6th")

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-19 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_item_late_exceptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "work_item_id", sa.String(36), sa.ForeignKey("child_work_items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("accepted_until", sa.String(30), nullable=False),
        sa.Column("credit_pct", sa.Float(), nullable=True),
        sa.Column("granted_note", sa.String(500), nullable=True),
        sa.Column("recorded_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "work_item_id", name="uq_work_item_late_exception"),
    )


def downgrade() -> None:
    op.drop_table("work_item_late_exceptions")
