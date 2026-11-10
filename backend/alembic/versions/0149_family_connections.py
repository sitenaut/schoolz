"""family_connections + family_connection_requests: an app reading one family's feed

billz, the owner's household app, connects with the same device flow as
Backpack Capture, approved by a super admin (routers/family_connections.py),
and reads GET /family/feed with the key it collects. Additive: two new
tables, read only by code in the same deploy.

Revision ID: 0149
Revises: 0148
Create Date: 2026-11-09 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0149"
down_revision: str | None = "0148"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "family_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_family_connections_user_id", "family_connections", ["user_id"])
    op.create_index("ix_family_connections_key_hash", "family_connections", ["key_hash"], unique=True)

    op.create_table(
        "family_connection_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_code", sa.String(16), nullable=False),
        sa.Column("device_code_hash", sa.String(64), nullable=False),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("requester_ip_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "family_connection_id",
            sa.String(36),
            sa.ForeignKey("family_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_family_connection_requests_user_code", "family_connection_requests", ["user_code"], unique=True)
    op.create_index(
        "ix_family_connection_requests_device_code_hash", "family_connection_requests", ["device_code_hash"], unique=True
    )
    op.execute("ALTER TABLE family_connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE family_connection_requests ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("family_connection_requests")
    op.drop_table("family_connections")
