"""seasonal: Wreaths Across America Day at Washington Crossing

Wreaths Across America's own site turns away every automated client,
schoolz's honest one included: every page, robots.txt too, answers with a bot
check only a browser gets past, so its location pages aren't read here.
Washington Crossing National Cemetery's wreaths are run by a local committee,
Washington Crossing Wreaths for Veterans, whose own site (wcwreaths.org, open
to crawlers) posts the whole 2026 schedule, and these facts come from it,
checked 2026-11-02. The other nearby cemeteries (Doyle, Beverly, Philadelphia)
post their 2026 times only on Wreaths Across America's site so far.

One row, for the Saturday: Friday's unpacking takes only high schoolers and
up, so a row starting then would point young kids at the wrong day.

Only what's missing is added: an attraction with the same season and name is
left as it is.

Revision ID: 0141
Revises: 0140
Create Date: 2026-11-02 15:30:00
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0141"
down_revision: str | None = "0140"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKED = date(2026, 11, 2)
_WAA_DAY = date(2026, 12, 19)

_ATTRACTIONS = [
    dict(
        season="winter",
        kind="volunteer",
        name="Wreaths Across America Day at Washington Crossing",
        venue="Washington Crossing National Cemetery",
        address="830 Highland Rd, Newtown, PA 18940",
        town="Newtown",
        latitude=40.2667,
        longitude=-74.90534,
        url="https://wcwreaths.org/waa-day-schedule-of-events/",
        ticket_url=None,
        starts_on=_WAA_DAY,
        ends_on=_WAA_DAY,
        open_dates=[_WAA_DAY],
        schedule="Sat Dec 19: wreath laying from 8:30am, and the ceremony at the flagpole circle at 11am. High schoolers and up can help unpack the wreaths Fri Dec 18 from 8:30am, and anyone can help pick them up on MLK Day, Mon Jan 18, from 8:30am; bring gloves for both.",
        price="Free.",
        ages="Everyone, with no registration. Each person 12 and up gets a voucher to lay up to six wreaths, and younger kids share a parent's.",
        note="Lay wreaths on veterans' graves with the local committee, Washington Crossing Wreaths for Veterans, saying each veteran's rank and name aloud. Traffic runs one way all day: come in by the Maintenance Entrance at the lower end of Highland Road, and carpool if you can.",
        source_url="https://wcwreaths.org/ceremonial-wreath-guidelines/",
    ),
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
