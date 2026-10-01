"""schools.healthepro_location/job_id - Health-e Pro menus (Maple Shade).

Revision ID: 0073
Revises: 0072
Create Date: 2026-09-30 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0073"
down_revision: Union[str, None] = "0072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("healthepro_location", sa.String(40), nullable=True))
    op.add_column(
        "schools",
        sa.Column("healthepro_job_id", sa.String(36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schools", "healthepro_job_id")
    op.drop_column("schools", "healthepro_location")
