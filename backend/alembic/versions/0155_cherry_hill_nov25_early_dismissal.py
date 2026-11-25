"""Cherry Hill's Nov 25 early dismissal, for its elementary and middle schools

The day before Thanksgiving is an early dismissal for the whole district,
but the only row on file was the high schools' (from their rotation
schedule): the district calendar feed has no entry for the day, and an
elementary newsletter's line for it had been dropped as a duplicate of the
high-school-only row (the rule fixed by content_extractor._calendar_says,
which only applies to newsletters read after it). Every elementary and
middle school's Today card said "Open" that morning. Confirmed by the
owner.

Adds one district row for elementary and middle schools, and retires the
single school's own copy saved by re-reading its newsletter, which the new
row covers. A database without the district gets nothing.

Revision ID: 0155
Revises: 0154
Create Date: 2026-11-25 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0155"
down_revision: str | None = "0154"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROW_ID = "c1a7e2b4-5d1f-4a86-9e33-1125202600ed"
_SCHOOL_COPY_ID = "bb56ea90-b875-417b-a8ab-a28176c94274"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO school_content_items
                (id, scope, district_id, category, title, description, start_date, is_all_day,
                 extracted_at, is_current, source, applies_to_school_types)
            SELECT CAST(:id AS VARCHAR), 'district', d.id, 'event', 'Early Dismissal',
                   'Early dismissal for staff and students before Thanksgiving Break.',
                   TIMESTAMPTZ '2026-11-25 05:00:00+00', true, now(), true, 'newsletter',
                   CAST(:types AS JSON)
            FROM districts d
            WHERE d.state = 'NJ' AND d.name = 'Cherry Hill Public Schools'
              AND NOT EXISTS (SELECT 1 FROM school_content_items WHERE id = CAST(:id AS VARCHAR))
            """
        ),
        {"id": _ROW_ID, "types": '["elementary", "middle"]'},
    )
    bind.execute(
        sa.text("UPDATE school_content_items SET is_current = false WHERE id = :id AND scope = 'school'"),
        {"id": _SCHOOL_COPY_ID},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE school_content_items SET is_current = true WHERE id = :id"), {"id": _SCHOOL_COPY_ID})
    # destructive-ok: removes only the one row this migration added
    bind.execute(sa.text("DELETE FROM school_content_items WHERE id = :id"), {"id": _ROW_ID})
