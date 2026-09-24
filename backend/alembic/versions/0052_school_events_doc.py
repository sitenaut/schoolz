"""school_events_doc: a school's own events-calendar Google Doc

Revision ID: 0052
Revises: 0051
Create Date: 2026-09-23 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("events_doc_url", sa.String(500), nullable=True))
    op.add_column("schools", sa.Column("events_doc_job_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_schools_events_doc_job_id", "schools", "scheduled_jobs", ["events_doc_job_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_schools_events_doc_job_id", "schools", type_="foreignkey")
    op.drop_column("schools", "events_doc_job_id")
    op.drop_column("schools", "events_doc_url")
