"""All-day ranges read by a model: end_date becomes the day after the last day

Every reader takes an all-day end_date as the ICS-style day after its last
day. The model-fed writers stored the printed last day instead, so "No
School Nov 5-6" closed only Nov 5. content_extractor.all_day_end fixes new
rows; this moves the stored ones, from the same four sources, whose end is
after their start. A one-day range (end on the start day) already reads
right and is left alone. Rewrites rows: a backup was taken first
(alembic/CLAUDE.md).

Revision ID: 0128
Revises: 0127
Create Date: 2026-10-23 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0128"
down_revision: str | None = "0127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The writers that now go through content_extractor.all_day_end.
SOURCES = ("newsletter", "givebacks_pta", "hs_activities_site", "community")

_LOCAL = "'America/New_York'"
FIX_SQL = f"""
UPDATE school_content_items
SET end_date = ((end_date AT TIME ZONE {_LOCAL})::date + 1)::timestamp AT TIME ZONE {_LOCAL}
WHERE is_all_day
  AND start_date IS NOT NULL
  AND end_date IS NOT NULL
  AND source IN :sources
  AND (end_date AT TIME ZONE {_LOCAL})::date > (start_date AT TIME ZONE {_LOCAL})::date
"""

UNDO_SQL = f"""
UPDATE school_content_items
SET end_date = ((end_date AT TIME ZONE {_LOCAL})::date - 1)::timestamp AT TIME ZONE {_LOCAL}
WHERE is_all_day
  AND start_date IS NOT NULL
  AND end_date IS NOT NULL
  AND source IN :sources
  AND (end_date AT TIME ZONE {_LOCAL})::date > (start_date AT TIME ZONE {_LOCAL})::date + 1
"""


def _run(sql: str) -> int:
    statement = sa.text(sql).bindparams(sa.bindparam("sources", expanding=True))
    return op.get_bind().execute(statement, {"sources": list(SOURCES)}).rowcount


def upgrade() -> None:
    print(f"0128: {_run(FIX_SQL)} all-day end date(s) moved to the day after their last day")


def downgrade() -> None:
    _run(UNDO_SQL)
