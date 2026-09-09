"""delayed opening time + seed high school bell times

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-08 23:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("delayed_opening_time", sa.String(length=20), nullable=True))
    # Confirmed 2026-09-08 from each school's own published bell schedule
    # PDF (west.chclc.org/our-school/chw-bell-schedule, "2026-2027 Bell
    # Schedule"; east.chclc.org/our-school/bell-schedule): both run
    # 7:30-2:30 regular, 9:30-2:30 delayed opening, 7:30-11:45 early
    # dismissal / half day. Keyed on website_url so a renamed school row
    # still matches; a no-op on a database without these schools.
    for domain in ("west.chclc.org", "east.chclc.org"):
        op.execute(
            f"""
            UPDATE schools SET start_time = '7:30 AM', end_time = '2:30 PM',
                early_dismissal_time = '11:45 AM', delayed_opening_time = '9:30 AM'
            WHERE website_url LIKE '%{domain}%'
            """
        )


def downgrade() -> None:
    op.drop_column("schools", "delayed_opening_time")
