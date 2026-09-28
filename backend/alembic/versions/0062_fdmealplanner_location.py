"""schools.fdmealplanner_location/job_id - FD MealPlanner menus (Haddon Township).

Revision ID: 0062
Revises: 0061
Create Date: 2026-09-27 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0062"
down_revision: Union[str, None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("fdmealplanner_location", sa.String(40), nullable=True))
    op.add_column(
        "schools",
        sa.Column("fdmealplanner_job_id", sa.String(36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schools", "fdmealplanner_job_id")
    op.drop_column("schools", "fdmealplanner_location")
