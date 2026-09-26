"""districts.towns (school picker) and districts.schoolcafe_shortname (menus)

Backfills Cherry Hill Public Schools so the picker has a town to show
before any other district exists.

Revision ID: 0056
Revises: 0055
Create Date: 2026-09-26 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("districts", sa.Column("towns", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("districts", sa.Column("schoolcafe_shortname", sa.String(100), nullable=True))
    op.add_column(
        "districts",
        sa.Column("schoolcafe_job_id", sa.String(36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
    )
    op.execute("""UPDATE districts SET towns = '["Cherry Hill"]' WHERE name = 'Cherry Hill Public Schools'""")


def downgrade() -> None:
    op.drop_column("districts", "schoolcafe_job_id")
    op.drop_column("districts", "schoolcafe_shortname")
    op.drop_column("districts", "towns")
