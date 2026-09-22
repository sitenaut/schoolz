"""student_specials: a child's elementary special for each rotation day

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-22 01:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_specials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rotation_day", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(100), nullable=False),
        sa.Column("teacher", sa.String(200), nullable=True),
        sa.Column("updated_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("student_id", "rotation_day", name="uq_student_special_day"),
    )
    op.create_index("ix_student_specials_student_id", "student_specials", ["student_id"])
    op.execute("ALTER TABLE student_specials ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_student_specials_student_id", table_name="student_specials")
    op.drop_table("student_specials")
