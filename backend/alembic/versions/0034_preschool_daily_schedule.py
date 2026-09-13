"""seed the shared CHPS preschool daily schedule across all preschool sites

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-12 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Transcribed 2026-09-12 from a "Cherry Hill Public Schools - Office of
# Preschool" printed schedule (the user's own copy - Site: Chesterbrook,
# Teacher: Kira Goldstein, Room 6). Per the user directly: this is the
# district's own shared preschool-day template, applied at every site with
# only the teacher/room filled in locally - not a Chesterbrook-specific
# schedule - so it's seeded across every tracked school_type='other' row,
# not just the one on the source document.
#
# Not independently verified per-site (e.g. whether Malberg, the
# district's own in-house Early Childhood Center rather than a classroom
# hosted inside a private partner's building, runs identical times) -
# applied uniformly on the user's explicit instruction ("add this to all
# preschools"). Worth a second look if a specific site's schedule is later
# found to differ.
#
# The source sheet's first two rows (8:15-8:45 "PLC for Preschool
# Teacher", 8:45-9:30 "Teacher Prep") are before children arrive - staff
# prep time, not part of any child's day - so they're deliberately
# excluded here; a parent's "what's my kid doing right now" chip should
# never show "Teacher Prep". start_time is therefore Arrival (9:30 AM),
# not the staff day's own start. "(NN minutes)" duration notes on the
# source sheet are dropped from each name - redundant with start/end,
# and several combined with their activity name would have exceeded even
# the widened 40-character period-name limit.
_BELL_PERIODS = {
    "regular": [
        {"name": "Arrival Choice/Table Top Activities", "start": "09:30", "end": "09:45"},
        {"name": "Large Group", "start": "09:45", "end": "10:05"},
        {"name": "Handwashing and Snack", "start": "10:05", "end": "10:25"},
        {"name": "Kickstart Literacy", "start": "10:25", "end": "10:45"},
        {"name": "Gross Motor", "start": "10:45", "end": "11:20"},
        {"name": "Choice Time", "start": "11:20", "end": "12:20"},
        {"name": "Handwashing", "start": "12:20", "end": "12:25"},
        {"name": "Lunch", "start": "12:25", "end": "12:55"},
        {"name": "Rest Time", "start": "12:55", "end": "13:45"},
        {"name": "Limited Choice/Small Group", "start": "13:45", "end": "14:15"},
        {"name": "Read Aloud", "start": "14:15", "end": "14:30"},
        {"name": "Gross Motor", "start": "14:30", "end": "15:00"},
        {"name": "Large Group / Departure", "start": "15:00", "end": "15:20"},
        {"name": "Pack-up and Dismissal", "start": "15:20", "end": "15:30"},
    ]
}


def upgrade() -> None:
    payload = json.dumps(_BELL_PERIODS)
    op.execute(
        f"UPDATE schools SET start_time = '9:30 AM', end_time = '3:30 PM', bell_periods = '{payload}'::json "
        "WHERE school_type = 'other'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE schools SET start_time = NULL, end_time = NULL, bell_periods = NULL WHERE school_type = 'other'"
    )
