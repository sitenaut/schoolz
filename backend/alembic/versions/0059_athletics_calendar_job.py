"""schools.athletics_calendar_job_id - tracks the ArbiterLive games-
calendar scan, created once athletics_url is a real /m/team/<id> page.

Revision ID: 0059
Revises: 0058
Create Date: 2026-09-27 03:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "schools",
        sa.Column("athletics_calendar_job_id", sa.String(36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schools", "athletics_calendar_job_id")
