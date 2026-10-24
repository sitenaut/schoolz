"""Per-connection cap on Backpack Capture connect requests

capture_device_requests.requester_ip_hash holds the reversible code of the
connection a Connect came from (never the address), so one script can no
longer fill the open-request cap and refuse every family's Connect.
Additive: one nullable column; rows already there simply have none.

Revision ID: 0129
Revises: 0128
Create Date: 2026-10-24 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0129"
down_revision: str | None = "0128"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("capture_device_requests", sa.Column("requester_ip_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("capture_device_requests", "requester_ip_hash")
