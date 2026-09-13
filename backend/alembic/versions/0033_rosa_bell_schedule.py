"""seed Rosa's bell schedule - the first middle school with one on file

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-12 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Transcribed 2026-09-12 from a photo of Rosa's own printed bell schedule
# (the user's kid's copy, not a district PDF - no auto-parse source exists
# for this one). CLAUDE.md had this as a known, unfilled gap: "Middle
# schools publish no bell schedule at all" (confirmed 2026-09-08) - this is
# the first one schoolz has on file.
#
# WIN ("What I Need") is a flexible intervention/enrichment block, common
# in NJ middle schools generally - not independently confirmed as Rosa's
# own name for it, but the paper's own row for it is formatted identically
# to every numbered period, which is the strongest signal that it's part
# of the regular day rather than a separate/optional add-on. Treated as
# such here: end_time is WIN's own end (3:00 PM), not period 9's (2:11 PM).
#
# Subject labels on the source photo (Science, Spanish, Math, ...) are one
# specific student's own rotation, not the school's - unlike a district's
# subject-by-period assignment, these vary per student, so only the times
# themselves (true for the whole school) are stored, matching how the high
# schools' block letters (A-H) are stored without any subject attached.
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
        "WHERE website_url LIKE '%rosa.chclc.org%'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE schools SET start_time = NULL, end_time = NULL, bell_periods = NULL "
        "WHERE website_url LIKE '%rosa.chclc.org%'"
    )
