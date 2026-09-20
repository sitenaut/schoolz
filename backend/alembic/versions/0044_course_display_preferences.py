"""per-account course display name/color preferences

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-20 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "course_display_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_key", sa.String(120), nullable=False),
        sa.Column("custom_name", sa.String(200), nullable=True),
        sa.Column("custom_color", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "course_key", name="uq_course_display_preference"),
    )
    op.create_index("ix_course_display_preferences_user_id", "course_display_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_course_display_preferences_user_id", table_name="course_display_preferences")
    op.drop_table("course_display_preferences")
