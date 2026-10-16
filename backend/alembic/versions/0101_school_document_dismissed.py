"""School documents: an admin can dismiss a file the scan got wrong

A dismissed document is never current, so the school page and the data
audit stop counting it, and the documents scan can't bring it back.

Revision ID: 0101
Revises: 0100
Create Date: 2026-10-16 02:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0101"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("school_documents", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("school_documents", "dismissed_at")
