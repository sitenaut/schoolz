"""school bell_periods (per-period table for East/West)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-09 14:00:00

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Transcribed 2026-09-09 from each school's own published "2026-2027 Bell
# Schedule" PDF (west.chclc.org/our-school/chw-bell-schedule, east.chclc.org
# /our-school/bell-schedule) - confirmed identical clock times for both
# schools; only which subject letter (A-H) lands in which numbered period
# varies by day rotation, not the times themselves.
_BELL_PERIODS = {
    "regular": [
        {"name": "1", "start": "07:30", "end": "08:27"},
        {"name": "2", "start": "08:31", "end": "09:28"},
        {"name": "3", "start": "09:32", "end": "10:29"},
        {"name": "L1", "start": "10:33", "end": "10:58"},
        {"name": "L2", "start": "11:02", "end": "11:27"},
        {"name": "4", "start": "11:31", "end": "12:28"},
        {"name": "5", "start": "12:32", "end": "13:29"},
        {"name": "6", "start": "13:33", "end": "14:30"},
    ],
    "delayed_opening": [
        {"name": "1", "start": "09:30", "end": "10:07"},
        {"name": "2", "start": "10:11", "end": "10:48"},
        {"name": "3", "start": "10:52", "end": "11:29"},
        {"name": "L1", "start": "11:33", "end": "11:58"},
        {"name": "L2", "start": "12:02", "end": "12:27"},
        {"name": "4", "start": "12:31", "end": "13:08"},
        {"name": "5", "start": "13:12", "end": "13:49"},
        {"name": "6", "start": "13:53", "end": "14:30"},
    ],
    "early_dismissal": [
        {"name": "1", "start": "07:30", "end": "08:00"},
        {"name": "2", "start": "08:04", "end": "08:34"},
        {"name": "3", "start": "08:38", "end": "09:08"},
        {"name": "L1", "start": "09:12", "end": "09:37"},
        {"name": "L2", "start": "09:41", "end": "10:06"},
        {"name": "4", "start": "10:10", "end": "10:39"},
        {"name": "5", "start": "10:43", "end": "11:12"},
        {"name": "6", "start": "11:16", "end": "11:45"},
    ],
}


def upgrade() -> None:
    op.add_column("schools", sa.Column("bell_periods", sa.JSON(), nullable=True))
    payload = json.dumps(_BELL_PERIODS)
    for domain in ("west.chclc.org", "east.chclc.org"):
        op.execute(f"UPDATE schools SET bell_periods = '{payload}'::json WHERE website_url LIKE '%{domain}%'")


def downgrade() -> None:
    op.drop_column("schools", "bell_periods")
