"""schools.nutrislice_location/job_id - Nutrislice menus (Cinnaminson).

Revision ID: 0079
Revises: 0078
Create Date: 2026-10-07 01:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0079"
down_revision: Union[str, None] = "0078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("nutrislice_location", sa.String(100), nullable=True))
    op.add_column(
        "schools",
        sa.Column("nutrislice_job_id", sa.String(36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schools", "nutrislice_job_id")
    op.drop_column("schools", "nutrislice_location")
