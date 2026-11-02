"""seasonal: soup kitchens where a parent can serve a meal

0139 kept to places a family can help at together, so it left out the soup
kitchens that take only adults. The owner asked for places where someone can
go and serve food, so these four join both season pages' "Volunteer & give
back" group as all-season places, like 0139's, with ages saying who they
take: Philly House and Broad Street Love take 18 and up, and St. Francis Inn
and Joseph's House of Camden post no age for serving a meal, so theirs say to
ask. Bethesda Project's holiday meals are left out: it has 15 sites and
schedules each meal by email, so there is no one place or time to list.

Facts are from each organizer's own pages, read by plain code with
schoolz's User-Agent (their robots.txt allows it), checked 2026-11-02. Where
a volunteer page gives a staff member's phone or email, the row links to the
page rather than copying them.

Only what's missing is added: an attraction with the same season and name is
left as it is.

Revision ID: 0142
Revises: 0141
Create Date: 2026-11-02 16:30:00
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0142"
down_revision: str | None = "0141"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKED = date(2026, 11, 2)


def _kitchens(season: str, starts: date, ends: date) -> list[dict]:
    common = dict(season=season, kind="volunteer", venue=None, starts_on=starts, ends_on=ends, open_dates=None, price="Free.")
    return [
        dict(
            common,
            name="Philly House",
            address="302 N 13th St, Philadelphia, PA 19107",
            town="Philadelphia",
            latitude=39.95824,
            longitude=-75.16019,
            url="https://www.phillyhouse.org/get-involved/volunteer/serve-a-meal",
            ticket_url="https://phillyhouse.volunteerhub.com/",
            schedule="Lunch and dinner are served every day of the year: pick a shift in its volunteer portal. Groups of six or more use its group form.",
            ages="18 and up on site; younger volunteers can help with its off-site projects (email to ask).",
            note="Serve lunch or dinner to people who are homeless or hungry, then sit down and share the meal with a guest. Wear closed-toe shoes, long pants and a shirt with sleeves, tie long hair back, and take no photos of guests.",
            source_url="https://www.phillyhouse.org/get-involved/volunteer",
        ),
        dict(
            common,
            name="Broad Street Love",
            address="315 S Broad St, Philadelphia, PA 19107",
            town="Philadelphia",
            latitude=39.94615,
            longitude=-75.16479,
            url="https://broadstreetlove.org/volunteer/",
            ticket_url="https://broadstreetlove.volunteerhub.com/vv2/",
            schedule="Weekdays: open shifts are on the calendar in its volunteer portal, with training at the start of each one.",
            ages="18 and up; groups of up to 16 adults.",
            note="Serve the daily meal restaurant-style, to guests seated at tables, or sort mail for the more than 5,000 people who use Broad Street Love as their address. Expect to be on your feet the whole shift.",
            source_url=None,
        ),
        dict(
            common,
            name="St. Francis Inn",
            address="2441 Kensington Ave, Philadelphia, PA 19125",
            town="Philadelphia",
            latitude=39.98692,
            longitude=-75.13067,
            url="https://stfrancisinn.org/volunteer/",
            ticket_url=None,
            schedule="Meal service Mon–Thu 4–6:15pm and Fri–Sun 11am–1:15pm, from set-up to clean-up; breakfast Tue and Thu 9am–1pm. Groups of fewer than eight.",
            ages="Not posted for meal service, so ask when you sign up; groups that stay overnight are high school age and up.",
            note="Seat, serve and bus tables at the Kensington meal that feeds about 300 people a day. Sign up through the volunteer email or group form on its page.",
            source_url=None,
        ),
        dict(
            common,
            name="Joseph's House of Camden",
            address="555 Atlantic Ave, Camden, NJ 08104",
            town="Camden",
            latitude=39.9288,
            longitude=-75.11857,
            url="https://www.jhoc.org/volunteer",
            ticket_url=None,
            schedule="Breakfast 5:30–6:30am or dinner 8–9:30pm; daytime help weekdays 9am–2pm in two-hour slots. Sign up through the contact on its volunteer page.",
            ages="Not posted; ask when you sign up.",
            note="Prepare and serve breakfast or dinner at Camden's shelter for people who are homeless, and stay for coffee and conversation with guests if you like. Groups can bring a casserole ready to heat, though food isn't required.",
            source_url=None,
        ),
    ]


# Same windows as 0139's all-season places.
_ATTRACTIONS = [
    *_kitchens("fall", date(2026, 11, 2), date(2026, 11, 29)),
    *_kitchens("winter", date(2026, 11, 13), date(2026, 12, 31)),
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
