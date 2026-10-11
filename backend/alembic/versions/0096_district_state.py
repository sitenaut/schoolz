"""A district is identified by its state and its name

districts.name was unique on its own. "Washington Township School District"
exists in several New Jersey counties and in other states, so the second one
could not be added. Every district tracked so far is in New Jersey, which is
the default and the backfill; uniqueness moves to (state, name).

Revision ID: 0096
Revises: 0095
Create Date: 2026-10-11 21:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0096"
down_revision: Union[str, None] = "0095"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("districts", sa.Column("state", sa.String(2), nullable=False, server_default="NJ"))
    op.drop_constraint("uq_districts_name", "districts", type_="unique")
    op.create_unique_constraint("uq_districts_state_name", "districts", ["state", "name"])


def downgrade() -> None:
    # Fails, deliberately, if two states now share a district name.
    op.drop_constraint("uq_districts_state_name", "districts", type_="unique")
    op.create_unique_constraint("uq_districts_name", "districts", ["name"])
    op.drop_column("districts", "state")
