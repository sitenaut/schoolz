"""students, guardian links, invites, notifications

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("student_id", sa.String(length=64), nullable=False),
        sa.Column("school_name", sa.String(length=255), nullable=True),
        sa.Column("match_key", sa.String(length=400), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_students_match_key", "students", ["match_key"], unique=True)

    op.create_table(
        "guardian_student_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("guardian_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("student_id", sa.String(length=36), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("linked_via", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guardian_user_id", "student_id", name="uq_guardian_student"),
    )

    op.create_table(
        "guardian_invites",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("student_id", sa.String(length=36), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("inviter_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("invitee_email", sa.String(length=255), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_guardian_invites_token", "guardian_invites", ["token"], unique=True)

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("student_id", sa.String(length=36), sa.ForeignKey("students.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("guardian_invites")
    op.drop_table("guardian_student_links")
    op.drop_table("students")
