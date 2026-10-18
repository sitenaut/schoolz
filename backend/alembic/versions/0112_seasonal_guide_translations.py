"""Seasonal guides: stored translations of title and note

Revision ID: 0112
Revises: 0111
Create Date: 2026-10-18 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0112"
down_revision: str | None = "0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("seasonal_guides", sa.Column("translations", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("seasonal_guides", "translations")
