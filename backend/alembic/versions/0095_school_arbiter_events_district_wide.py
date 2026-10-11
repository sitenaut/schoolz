"""Arbiter events that belong to the whole district

Audubon keeps one district calendar on its high school's Arbiter account (one
account is cheaper than one per school), so those events are the district's,
not the high school's. A school with this set stores its shown Arbiter events
district-scoped, and every school in the district shows them.

Revision ID: 0095
Revises: 0094
Create Date: 2026-10-11 20:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0095"
down_revision: Union[str, None] = "0094"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("arbiter_events_district_wide", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("schools", "arbiter_events_district_wide")
