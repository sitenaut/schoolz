"""chat_rate_windows: the chat's per-connection limit, shared by every API machine

Revision ID: 0115
Revises: 0114
Create Date: 2026-10-18 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0115"
down_revision: str | None = "0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_rate_windows",
        sa.Column("ip_hash", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_chat_rate_windows_window_start", "chat_rate_windows", ["window_start"])


def downgrade() -> None:
    op.drop_index("ix_chat_rate_windows_window_start", table_name="chat_rate_windows")
    op.drop_table("chat_rate_windows")
