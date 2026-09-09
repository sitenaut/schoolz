"""school logo_url

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-09 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("logo_url", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("schools", "logo_url")
