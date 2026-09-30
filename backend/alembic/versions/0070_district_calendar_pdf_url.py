"""district calendar_pdf_url

Revision ID: 0070
Revises: 0069
Create Date: 2026-09-29 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0070"
down_revision: Union[str, None] = "0069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("districts", sa.Column("calendar_pdf_url", sa.String(length=1000), nullable=True))
    op.add_column("districts", sa.Column("calendar_pdf_job_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(None, "districts", "scheduled_jobs", ["calendar_pdf_job_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_column("districts", "calendar_pdf_job_id")
    op.drop_column("districts", "calendar_pdf_url")
