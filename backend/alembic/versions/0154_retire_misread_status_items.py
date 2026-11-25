"""Retire eight newsletter-read status items that contradict the district calendar

One calendar image in a newsletter was misread on prod: "Winter Break" on
Dec 1-8 (the calendar's own is Dec 24 - Jan 1), which would have closed
every school's Today card on school days, plus an in-service day, an early
dismissal and three holidays on the wrong dates. Two more rows retell a day
the calendar already has, one of them ("Parent-Teacher Conferences (Early
Dismissal 1:00 PM)", an elementary's) with no school types, so both high
schools showed an early dismissal that is only preschool to grade 8.

New ones are stopped at save (content_extractor._calendar_says). The rows
are kept, only marked not current, as a superseded item is; ids that don't
exist (every database but prod) match nothing. The nightly backup
(docs/BACKUPS.md) holds them as they were.

Revision ID: 0154
Revises: 0153
Create Date: 2026-11-24 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0154"
down_revision: str | None = "0153"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDS = (
    "eab0e658-d3db-40ca-a165-292d1620510d",  # Winter Break, Dec 1-8
    "36274f4c-b887-42b9-969c-06cb3d62e329",  # In-Service Day (Lunar New Year), Feb 1 (calendar: Feb 5)
    "f1bb55b7-aaa5-4b9e-94ba-a90d6f49e190",  # Early Dismissal, Mar 26 (calendar: Mar 24, closed Mar 25-29)
    "845e04c0-be98-4eb8-ad72-fe192e9f2b68",  # Three Kings Day, Jan 26 (calendar: Jan 6)
    "90da5406-d475-41c6-923a-efa02e64d8d2",  # Eid al-Adha, May 1 (calendar: May 17)
    "de084d69-7efb-4c0d-9c97-ee31aee19187",  # Good Friday, Apr 2 (it is Mar 26)
    "41bcccd3-e539-4359-9c43-22c3f75880e1",  # Parent-Teacher Conferences (Early Dismissal 1:00 PM), all schools
    "878ca431-1878-46f5-a0f1-a56338491b75",  # School Closed, Nov 27 (calendar: Thanksgiving Break, Nov 26-27)
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE school_content_items SET is_current = false WHERE id IN :ids AND scope = 'district' AND is_current").bindparams(
            sa.bindparam("ids", expanding=True)
        ),
        {"ids": list(_IDS)},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE school_content_items SET is_current = true WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": list(_IDS)},
    )
