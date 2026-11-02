"""seasonal: adopt-a-family gift drives and USPS Operation Santa

The owner asked for "adopt a family" programs, where a family shops for
another family's holiday wish list. Two that a South Jersey family can join
this year go in both season pages' "Volunteer & give back" group: Alloy
Silverstein's Adopt A Family (a Cherry Hill accounting firm's drive, matched
through partner agencies) and Center For Family Services' Holiday Gift
Project in Voorhees. USPS Operation Santa, where you adopt a letter to Santa
and send the gift, is a link on the Christmas page, like 0139's shoebox
finder, and starts with that page's other guides so the season's badge
doesn't move.

Alloy Silverstein posts no sign-up deadline, only that its wish lists go out
around the middle of November, so it is listed through Nov 20, the week
before Thanksgiving, with the gift drop-off ("early December") in its
schedule.

Facts are from each organizer's own pages, read by plain code with
schoolz's User-Agent (their robots.txt allows it), checked 2026-11-02. Left
out for now: the Camden County Bar Foundation's Adopt-a-Family (its flier is
addressed to Bar members, and whether the public can join is unconfirmed),
the Salvation Army's Camden Kroc Center and Philadelphia Angel Tree (no 2026
dates posted yet), and Volunteers of America's Adopt a Family (closed for
2026).

Only what's missing is added: a guide with the same season and url, or an
attraction with the same season and name, is left as it is.

Revision ID: 0143
Revises: 0142
Create Date: 2026-11-02 18:00:00
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0143"
down_revision: str | None = "0142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKED = date(2026, 11, 2)
_ALLOY = "https://alloysilverstein.com/our-team/community-commitment/adopt/"


def _alloy(season: str) -> dict:
    return dict(
        season=season,
        kind="volunteer",
        name="Alloy Silverstein's Adopt A Family",
        venue=None,
        address="900 N Kings Hwy, Cherry Hill, NJ 08034",
        town="Cherry Hill",
        latitude=39.92268,
        longitude=-75.00099,
        url=_ALLOY,
        # The sign-up form is on the page itself.
        ticket_url=_ALLOY,
        starts_on=date(2026, 11, 2),
        ends_on=date(2026, 11, 20),
        open_dates=None,
        schedule="Sign up now: the wish lists go out around the middle of November, and the unwrapped gifts are due at its Cherry Hill or Hammonton office in early December.",
        price="You buy the gifts on your family's wish list.",
        ages="Families welcome: sign up as yourself, your family or your business.",
        note="A Cherry Hill accounting firm's holiday drive matches you, through partner agencies, with one of more than 50 South Jersey families in need, and you shop from the family's wish list: toys, or ShopRite and Walmart gift cards. Pick a family size, from one or two children to five or more.",
        source_url=None,
    )


def _gift_project(season: str, ends: date) -> dict:
    return dict(
        season=season,
        kind="volunteer",
        name="Center For Family Services Holiday Gift Project",
        venue=None,
        address="1 Alpha Ave, Voorhees, NJ 08043",
        town="Voorhees",
        latitude=39.8594,
        longitude=-75.0107,
        url="https://www.centerffs.org/event/holiday-gift-project",
        ticket_url=None,
        starts_on=date(2026, 11, 2),
        ends_on=ends,
        open_dates=None,
        schedule="Drop off unwrapped gifts at 1 Alpha Ave, Voorhees, Tue–Thu 10am–3pm through Fri Dec 11, or at the Cherry Hill Mall or Moorestown Mall management office, Mon–Fri 10am–4pm.",
        price="Whatever you give: money, gift cards or new, unwrapped gifts.",
        ages="Any age can give; donors don't meet the children, to protect their privacy.",
        note="Gifts for children, teens and young adults in Center For Family Services' group homes and shelters, and for families it serves. It asks first for money, so its staff can shop from each child's list and wrap; you or your company can sponsor the wish list of a whole safe home's children through the address on its page.",
        source_url=None,
    )


_ATTRACTIONS = [
    _alloy("fall"),
    _alloy("winter"),
    _gift_project("fall", date(2026, 11, 29)),
    _gift_project("winter", date(2026, 12, 11)),
]

# (season, title, publisher, url, note, starts_on, ends_on, sort_order), after
# 0139's shoebox finder so the banner headline stays 0138's.
_GUIDES = [
    (
        "winter",
        "USPS Operation Santa",
        "U.S. Postal Service",
        "https://www.uspsoperationsanta.com/",
        "Adopt a letter to Santa from a child or a family and send the gift. Sign up now; letters open for adoption Nov 16, and Dec 12 is the last day to adopt one and ship your gift. Letters come from all over the country.",
        date(2026, 11, 13),
        date(2026, 12, 12),
        55,
    ),
]

_guides = sa.table(
    "seasonal_guides",
    *[sa.column(c) for c in ("id", "season", "title", "publisher", "url", "note")],
    sa.column("starts_on", sa.Date()),
    sa.column("ends_on", sa.Date()),
    sa.column("sort_order", sa.Integer()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

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
    have_guides = {tuple(r) for r in conn.execute(sa.select(_guides.c.season, _guides.c.url))}
    have_attractions = {tuple(r) for r in conn.execute(sa.select(_attractions.c.season, _attractions.c.name))}
    now = datetime.now(UTC)
    guides = [
        {
            "id": str(uuid.uuid4()),
            "season": season,
            "title": title,
            "publisher": publisher,
            "url": url,
            "note": note,
            "starts_on": starts,
            "ends_on": ends,
            "sort_order": order,
            "created_at": now,
            "updated_at": now,
        }
        for season, title, publisher, url, note, starts, ends, order in _GUIDES
        if (season, url) not in have_guides
    ]
    attractions = [
        {"id": str(uuid.uuid4()), "scare_level": None, "verified_on": _CHECKED, "created_at": now, "updated_at": now, **row}
        for row in _ATTRACTIONS
        if (row["season"], row["name"]) not in have_attractions
    ]
    if guides:
        op.bulk_insert(_guides, guides)
    if attractions:
        op.bulk_insert(_attractions, attractions)


def downgrade() -> None:
    for season in {g[0] for g in _GUIDES}:
        urls = [g[3] for g in _GUIDES if g[0] == season]
        op.execute(_guides.delete().where(_guides.c.season == season, _guides.c.url.in_(urls)))
    for season in {a["season"] for a in _ATTRACTIONS}:
        names = [a["name"] for a in _ATTRACTIONS if a["season"] == season]
        op.execute(_attractions.delete().where(_attractions.c.season == season, _attractions.c.name.in_(names)))
