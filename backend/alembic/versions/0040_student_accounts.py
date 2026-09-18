"""student accounts: students.user_id + student_account_invites

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-14 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("students", sa.Column("user_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_students_user_id", "students", "users", ["user_id"], ["id"], ondelete="SET NULL")
    op.create_unique_constraint("uq_students_user_id", "students", ["user_id"])

    op.create_table(
        "student_account_invites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invited_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invitee_email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_student_account_invites_token", "student_account_invites", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_student_account_invites_token", table_name="student_account_invites")
    op.drop_table("student_account_invites")
    op.drop_constraint("uq_students_user_id", "students", type_="unique")
    op.drop_constraint("fk_students_user_id", "students", type_="foreignkey")
    op.drop_column("students", "user_id")
