"""school_content_items.applies_to_grad_years from titles that name a class

Every source but the class pages' own saved a high-school "Class of 2028
Movie Night" or "2027 Senior Trip" with no class, so the general calendar
and the family feed showed it to every family. New rows get their class at
save (models._grad_years_from_title); this tags the rows already saved, by
the same rule as of this revision: a high school's item, or a district item
not limited to other school types, whose title names one of the four
classes enrolled on the item's date.

A data backfill of a nullable column that is null on every row it touches;
the nightly backup (docs/BACKUPS.md) holds the rows as they were.

Revision ID: 0152
Revises: 0151
Create Date: 2026-11-12 00:00:00
"""
import re
from collections.abc import Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op

revision: str = "0152"
down_revision: str | None = "0151"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A copy of services/class_years.grad_years_in_title as it stands now: a
# migration runs the rule it was written with, whatever the code says later.
_ET = ZoneInfo("America/New_York")
_YEAR = r"(?:20\d\d|['‘’]\d\d)"
_CLASS_OF_RE = re.compile(rf"\bclass(?:es)?\s+of\s+({_YEAR}(?:\s*(?:,?\s*(?:and|&)|,|/|\+)\s*{_YEAR})*)", re.IGNORECASE)
_SENIOR_TRIP_RE = re.compile(r"\b(20\d\d)\s+senior\s+trip\b|\bsenior\s+trip\s+(20\d\d)\b", re.IGNORECASE)


def _enrolled_on(day: date) -> set[int]:
    start = day.year if day.month >= 7 else day.year - 1
    return {start + 1, start + 2, start + 3, start + 4}


def _grad_years(title: str, start: datetime | None) -> list[int] | None:
    found: set[int] = set()
    for m in _CLASS_OF_RE.finditer(title):
        found.update(int(y[-2:]) + 2000 if len(y) < 4 else int(y) for y in re.findall(_YEAR, m.group(1)))
    for m in _SENIOR_TRIP_RE.finditer(title):
        found.add(int(m.group(1) or m.group(2)))
    day = (start.astimezone(_ET) if start.tzinfo else start).date() if start else date.today()
    return sorted(found & _enrolled_on(day)) or None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT i.id, i.title, i.start_date
            FROM school_content_items i
            LEFT JOIN schools s ON s.id = i.school_id
            WHERE (i.applies_to_grad_years IS NULL OR i.applies_to_grad_years::text = 'null')
              AND (i.title ~* 'class(es)?\\s+of' OR i.title ~* 'senior\\s+trip')
              AND CASE
                    WHEN i.school_id IS NOT NULL THEN s.school_type = 'high'
                    ELSE i.applies_to_school_types IS NULL
                      OR i.applies_to_school_types::text = 'null'
                      OR i.applies_to_school_types::jsonb ? 'high'
                  END
            """
        )
    ).all()
    update = sa.text("UPDATE school_content_items SET applies_to_grad_years = :years WHERE id = :id").bindparams(
        sa.bindparam("years", type_=sa.JSON)
    )
    for item_id, title, start in rows:
        years = _grad_years(title, start)
        if years:
            bind.execute(update, {"id": item_id, "years": years})


def downgrade() -> None:
    # The rows tagged here can't be told from ones tagged at save since.
    pass
