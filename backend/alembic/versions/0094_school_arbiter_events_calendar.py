"""Schools that publish their own events on Arbiter

An Arbiter calendar carries /m/event/<id> items beside the /m/game/<id> games.
At Gateway they are the school's own events (field trips, Financial Aid Night);
at most schools they are team business (open gyms, team dinners, tryouts) and
belong with the hidden games. So showing them is a per-school setting, off by
default.

Revision ID: 0094
Revises: 0093
Create Date: 2026-10-11 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0094"
down_revision: Union[str, None] = "0093"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("arbiter_events_calendar", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("schools", "arbiter_events_calendar")
