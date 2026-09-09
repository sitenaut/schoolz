"""district hs_rotation_url

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-08 23:50:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("districts", sa.Column("hs_rotation_url", sa.String(length=1000), nullable=True))
    op.add_column("districts", sa.Column("hs_rotation_job_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(None, "districts", "scheduled_jobs", ["hs_rotation_job_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_column("districts", "hs_rotation_job_id")
    op.drop_column("districts", "hs_rotation_url")
