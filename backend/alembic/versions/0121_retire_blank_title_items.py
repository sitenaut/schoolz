"""Retire content items with an empty title

special_events.scan stored an entry for every blank or icon-only day of a
preschool's monthly calendar (October 2026: 19 rows from one PDF), each shown
as a nameless "EVENT" row on Today. The parser now skips them; this marks the
ones already stored not current, so nothing serves them. The rows stay (the
scan's "already processed this PDF" check finds them by link_url, so the
month isn't parsed again).

Revision ID: 0121
Revises: 0120
Create Date: 2026-10-20 00:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0121"
down_revision: str | None = "0120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE school_content_items SET is_current = false WHERE is_current AND btrim(title) = ''")


def downgrade() -> None:
    # Nothing worth restoring: the rows had no title to show.
    pass
