"""schools.special_events_calendar_url + special_events_scan_job_id

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-12 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("special_events_calendar_url", sa.String(length=500), nullable=True))
    op.add_column("schools", sa.Column("special_events_scan_job_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_schools_special_events_scan_job_id", "schools", "scheduled_jobs", ["special_events_scan_job_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_schools_special_events_scan_job_id", "schools", type_="foreignkey")
    op.drop_column("schools", "special_events_scan_job_id")
    op.drop_column("schools", "special_events_calendar_url")
