"""Admin-issued API keys for scripts and agents, plus device-flow login requests.

Revision ID: 0072
Revises: 0071
Create Date: 2026-09-30 16:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0072"
down_revision: Union[str, None] = "0071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("permissions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "api_key_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_code", sa.String(16), nullable=False),
        sa.Column("device_code_hash", sa.String(64), nullable=False),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("requested_ip", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("key_name", sa.String(100), nullable=True),
        sa.Column("permissions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("key_expires_in_days", sa.Integer, nullable=True),
        sa.Column("api_key_id", sa.String(36), sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_api_key_requests_user_code", "api_key_requests", ["user_code"], unique=True)
    op.create_index("ix_api_key_requests_device_code_hash", "api_key_requests", ["device_code_hash"], unique=True)
    op.execute("ALTER TABLE api_key_requests ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("api_key_requests")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")
