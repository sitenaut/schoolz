"""points_possible on child_work_items, from each assignment's detail page

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-20 17:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("child_work_items", sa.Column("points_possible", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("child_work_items", "points_possible")
