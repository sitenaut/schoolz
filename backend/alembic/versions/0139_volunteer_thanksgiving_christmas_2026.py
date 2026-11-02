"""seasonal: volunteering for Thanksgiving and Christmas 2026

Thanksgiving and Christmas are the seasons of giving, so both season pages
get a "Volunteer & give back" group (kind `volunteer`): days a family can
help out together, and places that take kids all season, each with the
youngest age the organizer allows. Facts are from each organizer's own
page, checked 2026-11-02; Love Your Park's main site and hours come from
the city's announcement, named in source_url.

Left out until someone checks them by hand, because their sites refuse
automated reads: Wreaths Across America (Dec 19 at the Doyle and Beverly
cemeteries, by search results), Toys for Tots, and the Food Bank of South
Jersey, whose robots.txt turns AI crawlers away. Also left out: what has
no 2026 dates posted (Salvation Army bell ringing, Jewish Family &
Children's Service holiday meal deliveries), places that take adults only
(Philabundance, Philly House, Broad Street Love), and Volunteers of
America's Adopt a Family, whose page gives no address or sign-up for its
gift volunteers.

Guides, links only as in 0081: the Volunteer Center of South Jersey's
Season of Service list, Idealist (where VolunteerMatch's listings moved in
2025) and Operation Christmas Child's drop-off finder.

Only what's missing is added: a guide with the same season and url, or an
attraction with the same season and name, is left as it is.

Revision ID: 0139
Revises: 0138
Create Date: 2026-11-02 12:00:00
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from alembic import op

revision: str = "0139"
down_revision: str | None = "0138"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKED = date(2026, 11, 2)


def _d(month: int, day: int) -> date:
    """A day of the 2026-27 season: April to December are 2026, January to March 2027."""
    return date(2027 if month <= 3 else 2026, month, day)


def _days(*spans) -> list[date]:
    """Every date in each span: (month, day) for one day, ((month, day), (month, day)) for a run of days."""
    out = []
    for span in spans:
        first, last = (span, span) if isinstance(span[0], int) else span
        start, end = _d(*first), _d(*last)
        out += [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return out


_SEASON_OF_SERVICE = "https://sjvolunteers.galaxydigital.com/need/index?s=1&need_init_id=16914"
_IDEALIST = "https://www.idealist.org/en/volunteer-in-cherry-hill-nj"

# (season, title, publisher, url, note, starts_on, ends_on, sort_order). After 0138's guides, so
# neither season's banner headline changes.
_GUIDES = [
    (
        "fall",
        "Season of Service 2026",
        "Volunteer Center of South Jersey",
        _SEASON_OF_SERVICE,
        "Holiday volunteering around South Jersey, from food drives to a Family Volunteer Day fair; filter it for family-friendly ones.",
        _d(11, 2),
        _d(11, 29),
        50,
    ),
    (
        "fall",
        "Volunteer in Cherry Hill Township, NJ",
        "Idealist",
        _IDEALIST,
        "Volunteer listings around South Jersey and Philadelphia, holiday meals among them. VolunteerMatch's listings moved here in 2025.",
        _d(11, 2),
        _d(11, 29),
        60,
    ),
    (
        "winter",
        "Find Your Shoebox Drop-off Location",
        "Samaritan's Purse",
        "https://www.samaritanspurse.org/operation-christmas-child/drop-off-locations/",
        "Operation Christmas Child: pack a shoebox of gifts for a child at home, then drop it off at a church near you during collection week, Nov 16–23. Search by ZIP code.",
        _d(11, 13),
        _d(11, 23),
        50,
    ),
    (
        "winter",
        "Season of Service 2026",
        "Volunteer Center of South Jersey",
        _SEASON_OF_SERVICE,
        "Holiday volunteering around South Jersey, from toy drives to a Christmas party for families that needs helpers; filter it for family-friendly ones.",
        _d(11, 13),
        _d(12, 31),
        60,
    ),
    (
        "winter",
        "Volunteer in Cherry Hill Township, NJ",
        "Idealist",
        _IDEALIST,
        "Volunteer listings around South Jersey and Philadelphia, Salvation Army bell ringing among them. VolunteerMatch's listings moved here in 2025.",
        _d(11, 13),
        _d(12, 31),
        70,
    ),
]


def _jra(season: str, day: tuple[int, int]) -> dict:
    """The Jewish Relief Agency's monthly packing Sunday, which starts with a family hour."""
    on = _d(*day)
    return dict(
        season=season,
        kind="volunteer",
        name="Jewish Relief Agency food box packing",
        venue="JRA warehouse",
        address="10980 Dutton Rd, Philadelphia, PA 19154",
        town="Philadelphia",
        latitude=40.0912,
        longitude=-74.98729,
        url="https://jewishrelief.org/volunteer-calendar-2",
        ticket_url="https://jewishrelief.org/register-to-volunteer",
        starts_on=on,
        ends_on=on,
        open_dates=[on],
        schedule=f"{on:%a %b} {on.day}: JRA Juniors 9–10am, then an all-ages packing shift 10–11:30am.",
        price="Free.",
        ages="JRA Juniors is for families with kids under 10, at a kid-friendly pace; the 10am shift is for all ages. Register ahead.",
        note="Pack the month's food boxes for families in need around Philadelphia; volunteer drivers then pick them up, Sunday to Tuesday, and deliver them.",
        source_url=None,
    )


def _all_season(season: str, starts: date, ends: date) -> list[dict]:
    """Places that take volunteers, kids among them, any week of the season."""
    return [
        dict(
            season=season,
            kind="volunteer",
            name="Cradles to Crayons Giving Factory",
            venue="Giving Factory",
            address="4700 Wissahickon Ave, Suite 142, Philadelphia, PA 19144",
            town="Philadelphia",
            latitude=40.01658,
            longitude=-75.17122,
            url="https://www.cradlestocrayons.org/philadelphia/take-action/volunteer/in-the-giving-factory/",
            ticket_url="https://vms.cradlestocrayons.org/",
            starts_on=starts,
            ends_on=ends,
            open_dates=None,
            schedule="Tue 6–8pm; Wed–Sat 10am–noon or 1–3pm. Two shifts a month per volunteer.",
            price="Free.",
            ages="5 and up; anyone under 18 needs an adult volunteering alongside them for the whole shift.",
            note="Sort and pack donated essentials into bundles for kids in need. Register in the volunteer portal first: only pre-registered volunteers get in.",
            source_url="https://www.cradlestocrayons.org/philadelphia/take-action/volunteer/resources/",
        ),
        dict(
            season=season,
            kind="volunteer",
            name="Caring for Friends",
            venue=None,
            address="12271 Townsend Rd, Philadelphia, PA 19154",
            town="Philadelphia",
            latitude=40.10267,
            longitude=-74.98477,
            url="https://www.caringforfriends.org/volunteer",
            ticket_url="https://volunteer.bloomerang.co/JE/y9z8wzmzp55c3x",
            starts_on=starts,
            ends_on=ends,
            open_dates=None,
            schedule="Shifts are in its volunteer portal; a group can pack Caring Bags at a place of its choosing.",
            price="Free.",
            ages="Snack bags from age 8, the kitchen from 12; under 16 with an adult.",
            note="Help in the kitchen or pack snack bags and Caring Bags for neighbors in need. Make an account in the volunteer portal, then pick a shift.",
            source_url=None,
        ),
        dict(
            season=season,
            kind="volunteer",
            name="Cathedral Kitchen",
            venue=None,
            address="1514 Federal St, Camden, NJ 08105",
            town="Camden",
            latitude=39.94415,
            longitude=-75.10285,
            url="https://cathedralkitchen.org/volunteer/",
            ticket_url="https://cathedralkitchen.volunteerhub.com/vv2/",
            starts_on=starts,
            ends_on=ends,
            open_dates=None,
            schedule="On-site shifts are posted two months ahead; projects from home any time.",
            price="Free.",
            ages="16 and up on site; younger kids can make placemats, centerpieces or utensil packets at home.",
            note="Help serve meals in Camden, or bring in a family project: decorated placemats or centerpieces for the dining room, utensil packets or sandwiches for to-go meals. Email before dropping projects off.",
            source_url=None,
        ),
        dict(
            season=season,
            kind="volunteer",
            name="MANNA",
            venue="Steven Korman Nutrition Center",
            address="420 N 20th St, Philadelphia, PA 19130",
            town="Philadelphia",
            latitude=39.96144,
            longitude=-75.17151,
            url="https://mannapa.org/volunteer/",
            ticket_url="https://mannapa.org/volunteer/volunteer-at-manna/",
            starts_on=starts,
            ends_on=ends,
            open_dates=None,
            schedule="Kitchen: weekdays 7–10am and 10am–1pm, Mon–Thu also 1:30–4:30pm, Mon also 5–8pm. Drivers: Tue–Fri, 8am–noon.",
            price="Free.",
            ages="14 and up; under 18 needs a parent's signed consent form.",
            note="Prepare food and pack meals in MANNA's kitchen, or drive meals to people's doorsteps around Philadelphia.",
            source_url="https://mannapa.org/volunteer/volunteer-groups/",
        ),
    ]


_ATTRACTIONS = [
    # November ("fall"): Thanksgiving's volunteer days, then places that take families all month.
    dict(
        season="fall",
        kind="volunteer",
        name="Love Your Park Fall Weekend",
        venue="Stephen Girard Park",
        address="2101 W Shunk St, Philadelphia, PA 19145",
        town="Philadelphia",
        latitude=39.9197,
        longitude=-75.18257,
        url="https://loveyourpark.org/events/lyp-fall-2026",
        ticket_url="https://loveyourpark.org/events/lyp-fall-2026",
        starts_on=_d(11, 13),
        ends_on=_d(11, 15),
        open_dates=_days(((11, 13), (11, 15))),
        schedule="Nov 13–15 at more than 100 city parks; the main cleanup, at Stephen Girard Park, is Sat Nov 14, 9am–1pm.",
        price="Free.",
        ages="Everyone is welcome.",
        note="Philadelphia's fall park cleanup: tend gardens and flower beds, care for trees and pick up litter, with tools, gloves and materials provided. Pick a park near you on the sign-up page.",
        source_url="https://www.phila.gov/2026-10-13-give-back-to-your-community-during-love-your-park-fall-weekend/",
    ),
    _jra("fall", (11, 15)),
    dict(
        season="fall",
        kind="volunteer",
        name="Family Volunteer Day Fair",
        venue="Rowan College of South Jersey, Behavioral Sciences Center",
        address="1400 Tanyard Rd, Sewell, NJ 08080",
        town="Sewell",
        latitude=39.788,
        longitude=-75.12621,
        url="https://sjvolunteers.galaxydigital.com/need/detail/?need_id=1326269",
        ticket_url="https://sjvolunteers.galaxydigital.com/need/detail/?need_id=1326269",
        starts_on=_d(11, 21),
        ends_on=_d(11, 21),
        open_dates=_days((11, 21)),
        schedule="Sat Nov 21, 10am–1pm.",
        price="Free.",
        ages="Individuals and families of all ages; register ahead.",
        note="The Volunteer Center of South Jersey's Family Volunteer Day: meet local nonprofits, then do hands-on service projects for the community right there.",
        source_url=None,
    ),
    dict(
        season="fall",
        kind="volunteer",
        name="Operation Turkey Philadelphia",
        venue="The Common Place",
        address="5736 Chester Ave, Philadelphia, PA 19143",
        town="Philadelphia",
        latitude=39.936,
        longitude=-75.22805,
        url="https://www.operationturkey.com/locations/philadelphia/",
        ticket_url="https://www.operationturkey.com/volunteer/",
        starts_on=_d(11, 25),
        ends_on=_d(11, 26),
        open_dates=_days((11, 25), (11, 26)),
        schedule="Wed Nov 25, 6–8pm: the Turkey Tailgate. Thanksgiving Day, 8am–noon: cook, pack and deliver meals.",
        price="Free.",
        ages="Kids are welcome with a parent or guardian; under 16, sign up by email.",
        note="Volunteers smoke the turkeys and get ready the night before, then cook, pack and deliver Thanksgiving meals to people who are homeless or in need. Join the volunteer network to get the details by email.",
        source_url=None,
    ),
    *_all_season("fall", _d(11, 2), _d(11, 29)),
    # Christmas ("winter"): JRA's December packing Sunday, and the same all-season places to the end of the year.
    _jra("winter", (12, 13)),
    *_all_season("winter", _d(11, 13), _d(12, 31)),
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
    # Only what's missing: a guide already there with the same season and url,
    # or an attraction with the same season and name (added by hand through
    # the admin API, say), is left as it is rather than doubled or overwritten.
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
        {
            "id": str(uuid.uuid4()),
            "scare_level": None,
            "verified_on": _CHECKED,
            "created_at": now,
            "updated_at": now,
            **row,
        }
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
