"""long_block bell variant for Cherry Hill East (rotation Days 5 and 6)

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-21 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import json


revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Days 5 and 6 run four ~87-minute blocks, not the six 57-minute slots in
# 0024's "regular" table (whose comment assumed the times never vary). Read
# off East's Genesis bell-format schedule print for 2026-27 - these are the
# school's clock times, the same for every student. West shares the
# rotation sheet but its long-block times aren't confirmed, so it's left
# without this variant (school_today then shows no period chip on those
# days rather than a wrong one). See docs/HS_SCHEDULE_FINDINGS.md.
_LONG_BLOCK = [
    {"name": "1", "start": "07:30", "end": "08:57"},
    {"name": "2", "start": "09:01", "end": "10:29"},
    {"name": "L1", "start": "10:33", "end": "10:58"},
    {"name": "L2", "start": "11:02", "end": "11:27"},
    {"name": "3", "start": "11:31", "end": "12:58"},
    {"name": "4", "start": "13:02", "end": "14:30"},
]


def upgrade() -> None:
    payload = json.dumps({"long_block": _LONG_BLOCK})
    op.execute(
        f"UPDATE schools SET bell_periods = (bell_periods::jsonb || '{payload}'::jsonb)::json "
        "WHERE website_url LIKE '%east.chclc.org%' AND bell_periods IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE schools SET bell_periods = (bell_periods::jsonb - 'long_block')::json "
        "WHERE website_url LIKE '%east.chclc.org%' AND bell_periods IS NOT NULL"
    )
