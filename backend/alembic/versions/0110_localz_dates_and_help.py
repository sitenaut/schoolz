"""Localz: dates a provider posts, and how people can help

Revision ID: 0110
Revises: 0109
Create Date: 2026-10-17 23:00:00

local_events.resource_service_id links a "Post a date" event to its
listing (deleted with it); resource_services.ways_to_help holds volunteer
roles, items to donate and a wish-list link. Both nullable.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0110"
down_revision: str | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("local_events", sa.Column("resource_service_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_local_events_resource_service_id", "local_events", "resource_services", ["resource_service_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_local_events_resource_service_id", "local_events", ["resource_service_id"])
    op.add_column("resource_services", sa.Column("ways_to_help", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("resource_services", "ways_to_help")
    op.drop_index("ix_local_events_resource_service_id", table_name="local_events")
    op.drop_constraint("fk_local_events_resource_service_id", "local_events", type_="foreignkey")
    op.drop_column("local_events", "resource_service_id")
