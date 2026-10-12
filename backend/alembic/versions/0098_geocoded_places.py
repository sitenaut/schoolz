"""Geocoder answers for local event venues

/local filters by distance, but most feeds give an address (or just a venue
name) rather than coordinates. local_events/locate.py geocodes those after
each refresh; this table remembers every answer - "no match" included, as
null coordinates - so each venue is asked about once.

Revision ID: 0098
Revises: 0097
Create Date: 2026-10-11 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0098"
down_revision: Union[str, None] = "0097"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geocoded_places",
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("looked_up_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("query"),
    )


def downgrade() -> None:
    op.drop_table("geocoded_places")
