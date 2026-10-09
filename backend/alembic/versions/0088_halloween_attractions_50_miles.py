"""Halloween 2026 attractions out to 50 miles from Cherry Hill

0085 stopped at about 30 miles. The owner set the edge at 50, which takes in
central Jersey, the far Philadelphia suburbs and northern Delaware. Facts are
from each venue's own site (checked 2026-10-09); where a venue posts its
nights only as a calendar image or its schedule page would not load, the
season window is from a dated news guide named in source_url and open_dates
is left null rather than guessed.

Revision ID: 0088
Revises: 0087
Create Date: 2026-10-09 12:00:00

"""
import uuid
from datetime import date, datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0088"
down_revision: Union[str, None] = "0087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECKED = date(2026, 10, 9)
_6ABC = "https://6abc.com/post/2026-haunted-house-heres-guide-spooky-events-pennsylvania-new-jersey-delaware/19806078/"


def _days(month: int, *days: int) -> list[date]:
    return [date(2026, month, d) for d in days]


_SEED = [
    dict(
        kind="haunt",
        name="Lincoln Mill Haunted House",
        venue=None,
        address="4100 Main Street, Philadelphia, PA 19127",
        town="Philadelphia",
        latitude=40.0222,
        longitude=-75.21841,
        url="https://lincolnmillhaunt.com/",
        ticket_url="https://lincolnmillhaunt2026.fearticket.com",
        starts_on=date(2026, 9, 26),
        ends_on=date(2026, 11, 7),
        open_dates=_days(9, 26) + _days(10, 3, 4, 9, 10, 11, 15, 16, 17, 18, 22, 23, 24, 25, 28, 29, 30, 31) + _days(11, 1, 7),
        schedule="Select nights through Nov 7; doors at 6:30 or 7pm, closing between 9:30 and 10:30pm.",
        price=None,
        scare_level="scary",
        ages=None,
        note="A high-intensity, story-driven haunt inside a historic mill in Manayunk.",
    ),
    dict(
        kind="haunt",
        name="Pennhurst Asylum",
        venue=None,
        address="601 N Church Street, Spring City, PA 19475",
        town="Spring City",
        latitude=40.18476,
        longitude=-75.55064,
        url="https://pennhurstasylum.com/",
        ticket_url="https://secure.interactiveticketing.com/1.43/ec53d5/#/select",
        starts_on=date(2026, 9, 25),
        ends_on=date(2026, 11, 7),
        open_dates=_days(9, 25, 26) + _days(10, 2, 3, 4, 9, 10, 11, 16, 17, 18, 23, 24, 25, 30, 31) + _days(11, 1, 6, 7),
        schedule="Friday and Saturday 6:30–10:30pm, Sunday 6:30–9:30pm. Timed tickets; arrive 15 minutes early.",
        price=None,
        scare_level="scary",
        ages=None,
        note="Four haunts on the grounds of a former state institution: the Asylum, the Tunnels, the Morgue and the Catacombs.",
    ),
    dict(
        kind="haunt",
        name="Field of Terror",
        venue="Kyle Family Farm",
        address="831 Windsor-Perrineville Road, East Windsor, NJ 08520",
        town="East Windsor",
        latitude=40.23602,
        longitude=-74.52113,
        url="https://www.fieldofterror.com/",
        ticket_url="https://www.fieldofterror.com/pricing.html",
        starts_on=date(2026, 9, 18),
        ends_on=date(2026, 11, 1),
        open_dates=None,
        schedule="Select nights through Nov 1, mostly Friday to Sunday. Their Dates & Hours page has the calendar.",
        price=None,
        scare_level="scary",
        ages=None,
        note="Several haunts on a working farm, including a haunted hayride and a cornfield walk; each is ticketed separately or as a pass.",
        source_url=_6ABC,
    ),
    dict(
        kind="haunt",
        name="Fright Fest",
        venue="Six Flags Great Adventure",
        address="1 Six Flags Boulevard, Jackson, NJ 08527",
        town="Jackson",
        latitude=40.14283,
        longitude=-74.44885,
        url="https://www.sixflags.com/greatadventure/events/fright-fest",
        ticket_url="https://www.sixflags.com/greatadventure/events/fright-fest",
        starts_on=date(2026, 9, 18),
        ends_on=date(2026, 11, 1),
        open_dates=None,
        schedule="Select nights through Nov 1; every Thursday night from Oct 8. Check the park calendar for the nights.",
        price=None,
        scare_level="scary",
        ages="Six Flags says it's not recommended for children under 13.",
        note="Haunted mazes, scare zones and shows inside the theme park after dark. Everyone needs a park ticket.",
    ),
    dict(
        kind="haunt",
        name="Frightland",
        venue=None,
        address="309 Port Penn Road, Middletown, DE 19709",
        town="Middletown, DE",
        latitude=39.52478,
        longitude=-75.64796,
        url="https://frightland.com/",
        ticket_url="https://frightland.com/frightland-tickets/",
        starts_on=date(2026, 10, 2),
        ends_on=date(2026, 11, 7),
        open_dates=None,
        schedule="Fridays, Saturdays and Sundays from Oct 2, plus Thursday Oct 22 and 29. Ticket booth 6–9pm (10pm on some Saturdays).",
        price="$45 Thursday, Friday and Sunday, $55 Saturday when bought online; covers all eight attractions and the midway rides.",
        scare_level="scary",
        ages=None,
        note="Eight haunts on a farm, with a haunted hayride, a barn, a prison and a cemetery, plus a carnival midway from Oct 9.",
        source_url="https://delawaretoday.com/things-to-do/kick-off-your-halloween-season-at-frightland-in-middletown/",
    ),
    dict(
        kind="trail",
        name="Scream Mountain",
        venue="Spring Mountain Adventures",
        address="757 Spring Mount Road, Spring Mount, PA 19478",
        town="Spring Mount",
        latitude=40.27313,
        longitude=-75.45059,
        url="https://www.springmountainadventures.com/scream-mountain/",
        ticket_url="https://springmountain-ecom.intouchelevate.com",
        starts_on=date(2026, 9, 25),
        ends_on=date(2026, 10, 31),
        open_dates=None,
        schedule="Select nights, 6:30–10pm. Their page has this year's calendar.",
        price="$35 for the chairlift walk and hayride, $30 hayride only. A tamer Starter Hayride leaves at 6pm for $12.",
        scare_level="scary",
        ages=None,
        note="A chairlift up a ski hill in the dark, then a walk back down a haunted trail, plus a haunted hayride.",
        source_url=_6ABC,
    ),
    dict(
        kind="festival",
        name="FallFest After Dark",
        venue="Shady Brook Farm",
        address="931 Stony Hill Road, Yardley, PA 19067",
        town="Yardley",
        latitude=40.22602,
        longitude=-74.88475,
        url="https://shadybrookfarm.com/pages/fallfest-after-dark",
        ticket_url="https://shadybrookfarm.com/collections/fallfest",
        starts_on=date(2026, 9, 11),
        ends_on=date(2026, 10, 30),
        open_dates=None,
        schedule="Starts at dusk on FallFest nights through Oct 30. Check their calendar for which nights.",
        price="$20–$35 depending on the date.",
        scare_level="family",
        ages="No live actors. The farm says the Haunted Barn and Alien Encounter may be scary for young children.",
        note="A Halloween light show, a flashlight corn maze, a haunted barn, bonfires and live music on a working farm.",
    ),
    dict(
        kind="haunt",
        name="The Curley's Haunt",
        venue="Concord Mall",
        address="4737 Concord Pike, Suite 510, Wilmington, DE 19803",
        town="Wilmington, DE",
        latitude=39.82544,
        longitude=-75.54503,
        url="https://www.thecurleyshaunt.com/",
        ticket_url="https://thecurleyshaunt.com/Schedule",
        starts_on=date(2026, 10, 2),
        ends_on=date(2026, 11, 8),
        open_dates=None,
        schedule="Select nights through Nov 8. Their Schedule page has the nights and times.",
        price=None,
        scare_level="scary",
        ages=None,
        note="An indoor haunted house in a mall, run to raise money for breast cancer support.",
        source_url=_6ABC,
    ),
    dict(
        kind="festival",
        name="Halloween House Philly",
        venue=None,
        address="901 Market Street, Philadelphia, PA 19107",
        town="Philadelphia",
        latitude=39.95139,
        longitude=-75.15522,
        url="https://www.phlvisitorcenter.com/things-to-do/halloween-house-philly",
        ticket_url="https://www.eventbrite.com/e/halloween-house-philly-tickets-1998015787004",
        starts_on=date(2026, 9, 25),
        ends_on=date(2026, 11, 1),
        open_dates=None,
        schedule="Open through Nov 1. Check the ticket page for the day's hours.",
        price=None,
        scare_level="family",
        ages="Billed as all ages, with no jump scares.",
        note="An indoor walk-through of decorated Halloween rooms in Center City, so it works in the rain.",
        source_url=_6ABC,
    ),
]

_table = sa.table(
    "seasonal_attractions",
    *[sa.column(c) for c in ("id", "season", "kind", "name", "venue", "address", "town", "latitude", "longitude", "url", "ticket_url")],
    sa.column("starts_on", sa.Date()),
    sa.column("ends_on", sa.Date()),
    sa.column("open_dates", postgresql.ARRAY(sa.Date())),
    *[sa.column(c) for c in ("schedule", "price", "scare_level", "ages", "note", "source_url")],
    sa.column("verified_on", sa.Date()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        _table,
        [
            {"id": str(uuid.uuid4()), "season": "halloween", "source_url": None, "verified_on": _CHECKED, "created_at": now, "updated_at": now, **row}
            for row in _SEED
        ],
    )


def downgrade() -> None:
    op.execute(_table.delete().where(_table.c.season == "halloween", _table.c.name.in_([row["name"] for row in _SEED])))
