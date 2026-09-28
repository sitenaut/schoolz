"""School coordinates + NWS gridpoint, for the Today card's weather fact.

Revision ID: 0061
Revises: 0060
Create Date: 2026-09-27 22:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("schools", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("schools", sa.Column("nws_grid", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("schools", "nws_grid")
    op.drop_column("schools", "longitude")
    op.drop_column("schools", "latitude")
