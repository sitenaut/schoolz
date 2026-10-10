"""Record who sent each community submission

The upload form is public, so every attempt - accepted or refused - gets a
row with the sender's IP, browser and the file's hash. Kept apart from
community_submissions so the record survives deleting a bad upload.

Revision ID: 0092
Revises: 0091
Create Date: 2026-10-10 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0092"
down_revision: Union[str, None] = "0091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "submission_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "submission_id",
            sa.String(36),
            sa.ForeignKey("community_submissions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("detail", sa.String(300), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("forwarded_for", sa.String(500), nullable=True),
        sa.Column("user_agent", sa.String(400), nullable=True),
        sa.Column("accept_language", sa.String(200), nullable=True),
        sa.Column("referer", sa.String(500), nullable=True),
        sa.Column("origin", sa.String(200), nullable=True),
        sa.Column("edge_region", sa.String(20), nullable=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submitter_name", sa.String(200), nullable=True),
        sa.Column("submitter_email", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(20), nullable=True),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_declared_type", sa.String(100), nullable=True),
        sa.Column("file_detected_type", sa.String(100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("file_sha256", sa.String(64), nullable=True),
        sa.Column("bot_check", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_submission_attempts_submission_id", "submission_attempts", ["submission_id"])
    op.create_index("ix_submission_attempts_ip", "submission_attempts", ["ip"])
    op.create_index("ix_submission_attempts_created_at", "submission_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_table("submission_attempts")
