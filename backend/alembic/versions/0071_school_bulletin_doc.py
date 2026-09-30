"""school bulletin_doc_url

Revision ID: 0071
Revises: 0070
Create Date: 2026-09-30 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0071"
down_revision: Union[str, None] = "0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("bulletin_doc_url", sa.String(length=500), nullable=True))
    op.add_column("schools", sa.Column("bulletin_doc_job_id", sa.String(length=36), nullable=True))
    op.add_column("schools", sa.Column("bulletin_content_hash", sa.String(length=64), nullable=True))
    op.create_foreign_key(None, "schools", "scheduled_jobs", ["bulletin_doc_job_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_column("schools", "bulletin_content_hash")
    op.drop_column("schools", "bulletin_doc_job_id")
    op.drop_column("schools", "bulletin_doc_url")
