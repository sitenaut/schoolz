"""survey_responses - the public parent survey behind /survey

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-12 13:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "survey_responses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("school_ids", sa.JSON(), nullable=False),
        sa.Column("satisfaction", sa.Integer(), nullable=True),
        sa.Column("pain_points", sa.JSON(), nullable=False),
        sa.Column("missing_info", sa.String(length=2000), nullable=True),
        sa.Column("comments", sa.String(length=5000), nullable=True),
        sa.Column("submitter_name", sa.String(length=200), nullable=True),
        sa.Column("submitter_email", sa.String(length=255), nullable=True),
        sa.Column("share_consent", sa.String(length=20), nullable=False, server_default="anonymous"),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_survey_responses_created_at", "survey_responses", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_survey_responses_created_at", table_name="survey_responses")
    op.drop_table("survey_responses")
