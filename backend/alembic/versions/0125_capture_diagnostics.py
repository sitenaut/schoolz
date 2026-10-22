"""capture_diagnostics: Backpack Capture's "Send logs to schoolz"

An update's step-by-step log, sent by the parent for troubleshooting
(routers/capture_devices.py). Additive: one new table, read only by code in
the same deploy.

Revision ID: 0125
Revises: 0124
Create Date: 2026-10-22 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0125"
down_revision: str | None = "0124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capture_diagnostics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "capture_device_id",
            sa.String(36),
            sa.ForeignKey("capture_devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extension_version", sa.String(20), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
    )
    op.create_index("ix_capture_diagnostics_user_id", "capture_diagnostics", ["user_id"])
    op.create_index("ix_capture_diagnostics_created_at", "capture_diagnostics", ["created_at"])
    op.execute("ALTER TABLE capture_diagnostics ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("capture_diagnostics")
