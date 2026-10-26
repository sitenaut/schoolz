"""district_transportation.daily_buses_note: who runs the daily buses

A district whose daily buses are someone else's says so on its
transportation page (Camden County Technical: "provided by the student's
sending school district"); the school page shows those words instead of an
office to call. Additive: one nullable column the previous release never
reads.

Revision ID: 0134
Revises: 0133
Create Date: 2026-10-26 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0134"
down_revision: str | None = "0133"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("district_transportation", sa.Column("daily_buses_note", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("district_transportation", "daily_buses_note")
