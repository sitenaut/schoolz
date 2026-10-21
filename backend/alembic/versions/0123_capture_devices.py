"""capture_devices + capture_device_requests: Backpack Capture's "Connect to schoolz"

A computer's extension gets its own key, approved by a signed-in person in
the schoolz tab it opens (routers/capture_devices.py). Additive: two new
tables, read only by code in the same deploy.

Revision ID: 0123
Revises: 0122
Create Date: 2026-10-21 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0123"
down_revision: str | None = "0122"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capture_devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_capture_devices_user_id", "capture_devices", ["user_id"])
    op.create_index("ix_capture_devices_key_hash", "capture_devices", ["key_hash"], unique=True)

    op.create_table(
        "capture_device_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_code", sa.String(16), nullable=False),
        sa.Column("device_code_hash", sa.String(64), nullable=False),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "capture_device_id",
            sa.String(36),
            sa.ForeignKey("capture_devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_capture_device_requests_user_code", "capture_device_requests", ["user_code"], unique=True)
    op.create_index(
        "ix_capture_device_requests_device_code_hash", "capture_device_requests", ["device_code_hash"], unique=True
    )
    op.execute("ALTER TABLE capture_devices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE capture_device_requests ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("capture_device_requests")
    op.drop_table("capture_devices")
