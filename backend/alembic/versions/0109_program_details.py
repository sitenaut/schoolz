"""Localz program details: in person or online, and how a program takes people

Revision ID: 0109
Revises: 0108
Create Date: 2026-10-17 20:00:00

Two nullable columns on resource_services, set by the provider portal
(resources/portal.py). A program's own schedule (monthly, every other week,
a season) lives in the existing `hours` JSON, so it needs no column.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0109"
down_revision: str | None = "0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resource_services", sa.Column("delivery", sa.String(length=20), nullable=True))
    op.add_column("resource_services", sa.Column("signup", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("resource_services", "signup")
    op.drop_column("resource_services", "delivery")
