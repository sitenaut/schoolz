"""schools.myschoolplate_location/job_id - Aramark MySchoolPlate menus (Camden City).

Revision ID: 0078
Revises: 0077
Create Date: 2026-10-06 15:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0078"
down_revision: Union[str, None] = "0077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("myschoolplate_location", sa.String(100), nullable=True))
    op.add_column(
        "schools",
        sa.Column("myschoolplate_job_id", sa.String(36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schools", "myschoolplate_job_id")
    op.drop_column("schools", "myschoolplate_location")
