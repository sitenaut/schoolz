"""add scheduled_jobs.run_once for one-shot jobs

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-13 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column("run_once", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("scheduled_jobs", "run_once", server_default=None)


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "run_once")
