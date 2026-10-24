"""rate_windows: per-account and per-connection limits shared by every API machine

For adding children (an auto-match links an account to a child, so student
IDs must not be guessable at speed) and the Kids View model calls. Additive:
a new table, nothing reads it until the code that writes it is deployed.

Revision ID: 0130
Revises: 0129
Create Date: 2026-10-24 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0130"
down_revision: str | None = "0129"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_windows",
        sa.Column("bucket", sa.String(40), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_rate_windows_window_start", "rate_windows", ["window_start"])
    op.execute("ALTER TABLE rate_windows ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_rate_windows_window_start", table_name="rate_windows")
    op.drop_table("rate_windows")
