"""apply Rosa's bell schedule to all middle schools

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-13 03:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same table as migration 0033 (Rosa International Middle School), applied
# to every school_type='middle' row rather than one. This is the owner's
# own decision, not an independently confirmed fact about Beck or Carusi's
# actual schedules - the three Cherry Hill middle schools have historically
# been documented as running on a shared district structure (unlike the
# preschools, where a shared template came from the district's own
# paperwork), but nobody has checked Beck's or Carusi's own bell times
# against this specific one. Worth a real check against each school's own
# published schedule if one ever surfaces, the same way Rosa's photo did.
_BELL_PERIODS = {
    "regular": [
        {"name": "1", "start": "08:00", "end": "08:57"},
        {"name": "2", "start": "09:01", "end": "09:53"},
        {"name": "3", "start": "09:57", "end": "10:49"},
        {"name": "4", "start": "10:53", "end": "11:19"},
        {"name": "5", "start": "11:22", "end": "11:48"},
        {"name": "6", "start": "11:51", "end": "12:17"},
        {"name": "7", "start": "12:20", "end": "12:46"},
        {"name": "8", "start": "12:49", "end": "13:15"},
        {"name": "9", "start": "13:19", "end": "14:11"},
        {"name": "WIN", "start": "14:15", "end": "15:00"},
    ]
}


def upgrade() -> None:
    payload = json.dumps(_BELL_PERIODS)
    op.execute(
        f"UPDATE schools SET start_time = '8:00 AM', end_time = '3:00 PM', bell_periods = '{payload}'::json "
        "WHERE school_type = 'middle'"
    )


def downgrade() -> None:
    # Reverting only clears Beck and Carusi - Rosa's own schedule (seeded
    # independently by migration 0033, from an actual source document) is
    # left in place rather than wiped out by rolling back this one.
    op.execute(
        "UPDATE schools SET start_time = NULL, end_time = NULL, bell_periods = NULL "
        "WHERE school_type = 'middle' AND slug != 'rosa'"
    )
