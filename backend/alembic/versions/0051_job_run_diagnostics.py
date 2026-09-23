"""job_run_diagnostics: machine/trace correlation + progress checkpointing

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-23 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_runs", sa.Column("machine_id", sa.String(64), nullable=True))
    op.add_column("job_runs", sa.Column("trace_id", sa.String(32), nullable=True))
    op.add_column("job_runs", sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("job_runs", "last_progress_at")
    op.drop_column("job_runs", "trace_id")
    op.drop_column("job_runs", "machine_id")
