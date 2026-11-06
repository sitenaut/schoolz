"""seasonal: Indian Acres Tree Farm's Winter Wonderland light trail

A parent pointed out Indian Acres in Medford as the cheaper farm for the
holidays, and its light trail went into local events (#540). The Christmas
page's light shows didn't have it, so the chatbot's find_seasonal_attractions
didn't either: asked "What's going on at Indian Acres?", it had nothing
seasonal to say.

Facts are from the farm's own pages (winterwonderland.indianacrestreefarm.com
and its FAQ, and indianacrestreefarm.com/winter-wonderland-trail; robots.txt
allows them), checked 2026-11-05. The nights are the trail site's calendar,
which the FAQ and the farm's page agree with: Dec 31 and Jan 1 are closed.
Ticket prices sit in the booking widget, not on any page, so none is given.

Only what's missing is added: an attraction with the same season and name
is left as it is.

Revision ID: 0147
Revises: 0146
Create Date: 2026-11-05 20:30:00
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from alembic import op

revision: str = "0147"
down_revision: str | None = "0146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKED = date(2026, 11, 5)


def _run(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


_NIGHTS = (
    _run(date(2026, 11, 20), date(2026, 11, 22))
    + _run(date(2026, 11, 27), date(2026, 12, 23))
    + _run(date(2026, 12, 26), date(2026, 12, 30))
    + _run(date(2027, 1, 2), date(2027, 1, 3))
)

_ATTRACTIONS = [
    dict(
        season="winter",
        kind="light_show",
        name="Winter Wonderland Illuminated Walking Trail",
        venue="Indian Acres Tree Farm",
        address="111 Tuckerton Rd, Medford, NJ 08055",
        town="Medford",
        latitude=39.87948,
        longitude=-74.8626,
        url="https://winterwonderland.indianacrestreefarm.com/",
        ticket_url="https://winterwonderland.indianacrestreefarm.com/pricing",
        starts_on=_NIGHTS[0],
        ends_on=_NIGHTS[-1],
        open_dates=_NIGHTS,
        schedule="Nov 20–22 and 27–30, Dec 1–23 and 26–30, Jan 2–3; Fri–Sat 5–9pm, other nights 5–8pm. Tickets are for an arrival time slot, entry closes 30 minutes before closing, and there are no refunds.",
        price=None,
        ages=None,
        note="A walking trail through the farm's woods and Christmas tree fields, lit with over 150,000 lights across more than 40 handmade scenes, about an hour's walk; you can go round twice. Photos with Santa (take your own) are included on select nights, Rudolph comes on some, and the Grinch most nights. Bonfires sell hot chocolate and s'mores kits. Wheelchair and stroller accessible; no dogs.",
        source_url="https://indianacrestreefarm.com/winter-wonderland-trail",
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
    names = [a["name"] for a in _ATTRACTIONS]
    op.execute(_attractions.delete().where(_attractions.c.season == "winter", _attractions.c.name.in_(names)))
