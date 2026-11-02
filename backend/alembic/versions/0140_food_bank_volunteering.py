"""seasonal: the Food Bank of South Jersey's warehouse volunteering

0139 left the Food Bank of South Jersey out: its robots.txt turns AI crawlers
away by name and refuses AI training. It allows every other crawler, though,
so on the owner's call its volunteer page was read by plain code with
schoolz's own User-Agent (schoolz-localz/1.0), not by an AI tool, and these
facts come from that page, checked 2026-11-02. Its warehouse takes families
with kids from 13, all season, so it joins both season pages' "Volunteer &
give back" group, like 0139's other all-season places.

Only what's missing is added: an attraction with the same season and name is
left as it is.

Revision ID: 0140
Revises: 0139
Create Date: 2026-11-02 14:00:00
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0140"
down_revision: str | None = "0139"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKED = date(2026, 11, 2)


def _food_bank(season: str, starts: date, ends: date) -> dict:
    return dict(
        season=season,
        kind="volunteer",
        name="Food Bank of South Jersey",
        venue="FBSJ warehouse",
        address="1501 John Tipton Blvd, Pennsauken, NJ 08110",
        town="Pennsauken",
        latitude=39.98158,
        longitude=-75.03889,
        url="https://foodbanksj.org/donate-time/",
        ticket_url="https://foodbanksj.org/donate-time/#VolForm",
        starts_on=starts,
        ends_on=ends,
        open_dates=None,
        schedule="Daytime warehouse shifts of up to eight people; weekends only as needed, and no evening shifts. Sign up ahead: no walk-ins.",
        price="Free.",
        ages="13 and up; 13–17 with a parent, guardian or chaperone there.",
        note="Pack and sort donated food in the warehouse, from assembling food boxes to repacking donations for the food bank's partner pantries in Burlington, Camden, Gloucester and Salem counties. Closed-toe shoes required.",
        source_url=None,
    )


# Same windows as 0139's all-season places.
_ATTRACTIONS = [
    _food_bank("fall", date(2026, 11, 2), date(2026, 11, 29)),
    _food_bank("winter", date(2026, 11, 13), date(2026, 12, 31)),
]

_attractions = sa.table(
    "seasonal_attractions",
    *[sa.column(c) for c in ("id", "season", "kind", "name", "venue", "address", "town", "latitude", "longitude", "url", "ticket_url")],
    sa.column("starts_on", sa.Date()),
    sa.column("ends_on", sa.Date()),
    sa.column("open_dates", sa.ARRAY(sa.Date())),
    *[sa.column(c) for c in ("schedule", "price", "scare_level", "ages", "note", "source_url")],
    sa.column("verified_on", sa.Date()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    conn = op.get_bind()
    have = {tuple(r) for r in conn.execute(sa.select(_attractions.c.season, _attractions.c.name))}
    now = datetime.now(UTC)
    rows = [
        {"id": str(uuid.uuid4()), "scare_level": None, "verified_on": _CHECKED, "created_at": now, "updated_at": now, **row}
        for row in _ATTRACTIONS
        if (row["season"], row["name"]) not in have
    ]
    if rows:
        op.bulk_insert(_attractions, rows)


def downgrade() -> None:
    for season in {a["season"] for a in _ATTRACTIONS}:
        names = [a["name"] for a in _ATTRACTIONS if a["season"] == season]
        op.execute(_attractions.delete().where(_attractions.c.season == season, _attractions.c.name.in_(names)))
