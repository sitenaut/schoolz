"""scheduled_jobs.run_requested_at: a run-now waiting for the scheduler

Revision ID: 0114
Revises: 0113
Create Date: 2026-10-18 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0114"
down_revision: str | None = "0113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scheduled_jobs", sa.Column("run_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "run_requested_at")
