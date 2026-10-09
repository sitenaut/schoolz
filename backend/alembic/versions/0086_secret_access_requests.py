"""secret_access_requests - approve use of the prod secrets vault from the admin

Revision ID: 0086
Revises: 0085
Create Date: 2026-10-08 21:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0086"
down_revision: Union[str, None] = "0085"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "secret_access_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_code", sa.String(16), nullable=False),
        sa.Column("device_code_hash", sa.String(64), nullable=False),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("command", sa.String(1000), nullable=False),
        sa.Column("secret_names", postgresql.JSONB(), nullable=False),
        sa.Column("requested_ip", sa.String(64), nullable=True),
        sa.Column("requested_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", sa.String(36), sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_secret_access_requests_user_code", "secret_access_requests", ["user_code"], unique=True)
    op.create_index("ix_secret_access_requests_device_code_hash", "secret_access_requests", ["device_code_hash"], unique=True)
    op.create_index("ix_secret_access_requests_status", "secret_access_requests", ["status"])
    op.create_index("ix_secret_access_requests_created_at", "secret_access_requests", ["created_at"])


def downgrade() -> None:
    op.drop_table("secret_access_requests")
