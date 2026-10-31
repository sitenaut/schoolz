"""email_scanners.last_run: what a scanner's latest run found, by count

A run only said "scanned 100 new message(s), 0 processed ok", which cannot
tell a filter that matches the wrong mail from links a scan refuses. This
holds the search it ran and the tallies (emails matched and new, links
kept, newsletters added, click-tracking links skipped) for the admin page.
Counts only: nothing from a message. Additive: one nullable column the
previous release never reads.

Revision ID: 0137
Revises: 0136
Create Date: 2026-10-31 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0137"
down_revision: str | None = "0136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("email_scanners", sa.Column("last_run", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("email_scanners", "last_run")
