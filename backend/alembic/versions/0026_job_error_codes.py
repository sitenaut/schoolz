"""job run/scheduled job error codes

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-11 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_runs", sa.Column("error_code", sa.String(length=40), nullable=True))
    op.add_column("job_runs", sa.Column("error_stage", sa.String(length=20), nullable=True))
    op.create_index("ix_job_runs_error_code", "job_runs", ["error_code"])
    op.add_column("scheduled_jobs", sa.Column("last_error_code", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "last_error_code")
    op.drop_index("ix_job_runs_error_code", table_name="job_runs")
    op.drop_column("job_runs", "error_stage")
    op.drop_column("job_runs", "error_code")
