"""child_work_items.status_seen_at: when a Classwork list last showed the item

A Classwork list marks every finished item, so a row there without a label
means the work isn't finished (unsubmitted, say). This records when that
reading was taken, so a newer one can clear a stale "Turned in" and an older
one arriving late can't. Additive: one nullable column.

Revision ID: 0126
Revises: 0125
Create Date: 2026-10-22 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0126"
down_revision: str | None = "0125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("child_work_items", sa.Column("status_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("child_work_items", "status_seen_at")
