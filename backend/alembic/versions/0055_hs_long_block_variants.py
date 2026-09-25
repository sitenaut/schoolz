"""long-block bell variants: West's long_block, and delayed-opening /
early-dismissal long-block tables for both high schools

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-25 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import json


revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Transcribed from West's own "Cherry Hill High School West 2026-2027 Bell
# Schedule" PDF (west.chclc.org/our-school/chw-bell-schedule), which prints
# Days 5-6 (four long blocks) for all three day types. Its regular,
# delayed-opening and early-dismissal six-block tables match what 0024 already
# holds for West minute for minute, and its regular long-block table matches
# East's (0046, from East's Genesis bell print) - so the two schools share one
# timetable, and 0046's "West's long-block times aren't confirmed" is now
# answered.
#
# East's own bell-schedule PDF (east.chclc.org/our-school/bell-schedule,
# linked as 2024-25 but identical to West's 2026-27 sheet in every cell but
# one) prints the same delayed and half-day long-block tables. The one
# difference is its second long block starting 9:02; East's 2026-27 Genesis
# print and West's 2026-27 PDF both say 9:01, which 0046 already has.
_LONG_BLOCK = [
    {"name": "1", "start": "07:30", "end": "08:57"},
    {"name": "2", "start": "09:01", "end": "10:29"},
    {"name": "L1", "start": "10:33", "end": "10:58"},
    {"name": "L2", "start": "11:02", "end": "11:27"},
    {"name": "3", "start": "11:31", "end": "12:58"},
    {"name": "4", "start": "13:02", "end": "14:30"},
]
_LONG_BLOCK_DELAYED = [
    {"name": "1", "start": "09:30", "end": "10:28"},
    {"name": "2", "start": "10:32", "end": "11:29"},
    {"name": "L1", "start": "11:33", "end": "11:58"},
    {"name": "L2", "start": "12:02", "end": "12:27"},
    {"name": "3", "start": "12:31", "end": "13:28"},
    {"name": "4", "start": "13:32", "end": "14:30"},
]
# The Dec 4 "6 (Early Dismissal - Afternoon PD)" case docs/HS_SCHEDULE_FINDINGS.md
# called unmodeled.
_LONG_BLOCK_EARLY = [
    {"name": "1", "start": "07:30", "end": "08:17"},
    {"name": "2", "start": "08:21", "end": "09:08"},
    {"name": "L1", "start": "09:12", "end": "09:37"},
    {"name": "L2", "start": "09:41", "end": "10:06"},
    {"name": "3", "start": "10:10", "end": "10:55"},
    {"name": "4", "start": "10:59", "end": "11:45"},
]

_BOTH = "(website_url LIKE '%west.chclc.org%' OR website_url LIKE '%east.chclc.org%')"


def _merge(where: str, variants: dict) -> None:
    payload = json.dumps(variants)
    op.execute(
        f"UPDATE schools SET bell_periods = (bell_periods::jsonb || '{payload}'::jsonb)::json "
        f"WHERE {where} AND bell_periods IS NOT NULL"
    )


def upgrade() -> None:
    _merge("website_url LIKE '%west.chclc.org%'", {"long_block": _LONG_BLOCK})
    _merge(_BOTH, {"long_block_delayed_opening": _LONG_BLOCK_DELAYED, "long_block_early_dismissal": _LONG_BLOCK_EARLY})


def downgrade() -> None:
    op.execute(
        "UPDATE schools SET bell_periods = (bell_periods::jsonb - 'long_block_delayed_opening' - 'long_block_early_dismissal')::json "
        f"WHERE {_BOTH} AND bell_periods IS NOT NULL"
    )
    op.execute(
        "UPDATE schools SET bell_periods = (bell_periods::jsonb - 'long_block')::json "
        "WHERE website_url LIKE '%west.chclc.org%' AND bell_periods IS NOT NULL"
    )
