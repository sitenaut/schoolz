"""schools.staff_directory_url - a staff directory published as a PDF table (Camden's Eastside High).

Revision ID: 0077
Revises: 0076
Create Date: 2026-10-06 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0077"
down_revision: Union[str, None] = "0076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("staff_directory_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("schools", "staff_directory_url")
