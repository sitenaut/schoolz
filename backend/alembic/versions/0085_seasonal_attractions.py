"""seasonal_attractions - haunts, flashlight mazes, light shows, Santa

Places open for a season, which the local events feeds miss. Seeds Halloween
2026, South Jersey and the Philadelphia side, from each venue's own site
(checked 2026-10-08; dates that a venue posts only as a calendar image were
read from that image), or a dated news item
where the venue hasn't posted this year's dates - see models.SeasonalAttraction.

Also links two more Halloween guides (as in 0084, links only, never scanned:
FrightMaps' terms forbid scraping, and its listings are mostly private home
addresses; The Scare Factor reserves all rights and rejects scripted requests).

Revision ID: 0085
Revises: 0084
Create Date: 2026-10-08 18:00:00

"""
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0085"
down_revision: Union[str, None] = "0084"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECKED = date(2026, 10, 8)


def _oct(*days: int) -> list[date]:
    return [date(2026, 10, d) for d in days]


def _weekdays(start: date, end: date, weekdays: set[int]) -> list[date]:
    """Every date in [start, end] whose weekday() is in `weekdays` (Mon=0)."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() in weekdays]


_SEED = [
    dict(
        kind="haunt",
        name="Night of Terror",
        venue="Creamy Acres Farm",
        address="448 Lincoln Mill Road, Mullica Hill, NJ 08062",
        town="Mullica Hill",
        latitude=39.70401,
        longitude=-75.25086,
        url="https://www.nightofterror.com/",
        ticket_url="https://www.nightofterror.com/tickets.html",
        starts_on=date(2026, 10, 2),
        ends_on=date(2026, 10, 31),
        open_dates=_oct(2, 3, 9, 10, 15, 16, 17, 22, 23, 24, 29, 30, 31),
        schedule="Thursday, Friday and Saturday nights in October from 6:30pm; closed Sundays.",
        price="$40 general admission; buy timed tickets online in advance.",
        scare_level="scary",
        ages="Under 18s need an adult with them.",
        note="Four haunted attractions on a dairy farm, plus a separate haunted paintball hayride ($30, riders 48\" and up).",
    ),
    dict(
        kind="haunt",
        name="HallowSpire",
        venue=None,
        address="231 Landing Street, Southampton, NJ 08088",
        town="Southampton",
        latitude=39.94214,
        longitude=-74.76904,
        url="https://hallowspire.com/",
        ticket_url="https://hallowspire.com/tickets/",
        starts_on=date(2026, 9, 25),
        ends_on=date(2026, 11, 1),
        open_dates=None,
        schedule="Select nights through Nov 1; gates open at 6pm (6:30pm through Oct 3). Check their tickets page for the nights.",
        price=None,
        scare_level="scary",
        ages="The venue says it's best for ages 10 and up and not for young children.",
        note="A Jersey Devil terror trail, a haunted corn maze and a forgotten-circus haunt on one ticket.",
    ),
    dict(
        kind="hayride",
        name="Scullville Fire Co. Haunted Hayride & Maze",
        venue="Fleming's Junkyard",
        address="353 Zion Road, Egg Harbor Township, NJ 08234",
        town="Egg Harbor Township",
        latitude=39.35938,
        longitude=-74.64288,
        url="https://scullvillefire.org/hayride/",
        ticket_url="https://scullvillefire.org/hayride/",
        starts_on=date(2026, 9, 25),
        ends_on=date(2026, 10, 25),
        open_dates=_weekdays(date(2026, 9, 25), date(2026, 10, 25), {4, 5, 6}),
        schedule="Friday to Sunday through Oct 25; ticket booth 7–10pm Friday and Saturday, 7–9pm Sunday.",
        price="$15 hayride, $10 maze, $20 for both.",
        scare_level="scary",
        ages=None,
        note="A volunteer fire company's haunted hayride through the woods and a junkyard, with a haunted maze.",
    ),
    dict(
        kind="haunt",
        name="The Haunting on High Street",
        venue="Burlington County Prison Museum",
        address="128 High Street, Mount Holly, NJ 08060",
        town="Mount Holly",
        latitude=39.99572,
        longitude=-74.78835,
        url="https://www.prisonmuseum.net/",
        ticket_url=None,
        starts_on=date(2026, 10, 16),
        ends_on=date(2026, 10, 31),
        open_dates=_oct(16, 17, 23, 24, 30, 31),
        schedule="Friday and Saturday nights, Oct 16–31, 7–10pm.",
        price=None,
        scare_level=None,
        ages=None,
        note="New this year: a haunted walk through a jail that's over two centuries old.",
    ),
    dict(
        kind="trail",
        name="Camden County 4-H Haunted Walk",
        venue="Camden County Office of Sustainability (Lakeland)",
        address="508 Lakeland Road, Blackwood, NJ 08012",
        town="Blackwood",
        latitude=39.78594,
        longitude=-75.06879,
        url="https://camden.njaes.rutgers.edu/4h/",
        ticket_url="https://www.zeffy.com/en-US/ticketing/2026-camden-county-4-h-haunting-haunted-walk",
        starts_on=date(2026, 10, 16),
        ends_on=date(2026, 10, 17),
        open_dates=_oct(16, 17),
        schedule="Friday and Saturday, Oct 16–17, 7–10:30pm.",
        price="$10 a person, online or at the door.",
        scare_level="mild",
        ages="Suggested for kids 6 and up.",
        note="4-H's biggest fundraiser of the year, with a DJ and a magic show at 8:30 each night.",
        source_url="https://wjrz.com/2026/10/02/support-youth-education-at-camden-county-4-hs-haunted-walk-fundraiser-october-16-17/",
    ),
    dict(
        kind="trail",
        name="Fear in the Forest",
        venue="A blueberry farm off Route 70",
        address="182 City Line Road, Browns Mills, NJ 08015",
        town="Browns Mills",
        latitude=39.92699,
        longitude=-74.48732,
        url="https://fearintheforest.weebly.com/",
        ticket_url=None,
        starts_on=date(2026, 10, 23),
        ends_on=date(2026, 10, 24),
        open_dates=_oct(23, 24),
        schedule="Two nights only, opening at dark; the gate closes at 10pm.",
        price="Tickets at the gate, cash only.",
        scare_level="scary",
        ages="The family that runs it says it's scary; too much for young kids.",
        note="A half-mile haunted trail through the woods and bogs, with live music. Dates from local listings; their own page shows them as an image.",
        source_url="https://6abc.com/post/2026-haunted-house-heres-guide-spooky-events-pennsylvania-new-jersey-delaware/19806078/",
    ),
    dict(
        kind="corn_maze",
        name="Flashlight Corn Maze",
        venue="Coombs Barnyard",
        address="20 Route 77, Elmer, NJ 08318",
        town="Elmer",
        latitude=39.55984,
        longitude=-75.24006,
        url="https://coombsbarnyard.com/public-events/",
        ticket_url="https://coombsbarnyard.com/public-events/",
        starts_on=date(2026, 10, 2),
        ends_on=date(2026, 10, 31),
        open_dates=_oct(2, 3, 9, 10, 11, 16, 17, 23, 24, 30, 31),
        schedule="Weekend evenings in October, 6:30–9pm.",
        price="$10.",
        scare_level="family",
        ages="Not scary: a corn maze in the dark with flashlights.",
        note="Bring a flashlight. The farm also runs daytime fall activities.",
    ),
    # Philadelphia side - /local covers it too. All within ~25 miles of Cherry Hill; Frightland (DE) and
    # Pennhurst (Spring City) are about twice that and left out.
    dict(
        kind="haunt",
        name="Fright Factory",
        venue=None,
        address="38 Jackson Street, Philadelphia, PA 19148",
        town="Philadelphia",
        latitude=39.92011,
        longitude=-75.14694,
        url="https://frightfactoryphilly.com/",
        ticket_url="https://frightfactoryphilly.com/",
        starts_on=date(2026, 10, 2),
        ends_on=date(2026, 11, 7),
        open_dates=_oct(2, 3, 4, 9, 10, 11, 16, 17, 18, 22, 23, 24, 25, 29, 30, 31) + [date(2026, 11, 1), date(2026, 11, 6), date(2026, 11, 7)],
        schedule="Select nights Oct 2 – Nov 7; 7:30–10pm Sunday to Thursday, 7:30–11pm Friday and Saturday. Open rain or shine.",
        price=None,
        scare_level="scary",
        ages=None,
        note="Three themed haunts in a 120-year-old South Philly warehouse; billed as high-scare.",
    ),
    dict(
        kind="haunt",
        name="Halloween Nights",
        venue="Eastern State Penitentiary",
        address="2027 Fairmount Avenue, Philadelphia, PA 19130",
        town="Philadelphia",
        latitude=39.96732,
        longitude=-75.17091,
        url="https://www.easternstate.org/halloween",
        ticket_url="https://www.easternstate.org/halloween/schedule-pricing",
        starts_on=_CHECKED,
        ends_on=date(2026, 11, 7),
        open_dates=None,
        schedule="Select nights through Nov 7, by half-hour entry time; rain or shine. Check their schedule for the nights.",
        price="Cheapest online; no refunds.",
        scare_level=None,
        ages=None,
        note="Haunted houses, shows and a speakeasy inside the old penitentiary.",
    ),
    dict(
        kind="hayride",
        name="Valley of Fear & Original Haunted Hayride",
        venue="Phoenix Sport Club",
        address="301 W Bristol Road, Feasterville, PA 19053",
        town="Feasterville",
        latitude=40.16548,
        longitude=-74.99568,
        url="https://www.valleyoffear.com/",
        ticket_url="https://www.valleyoffear.com/",
        starts_on=date(2026, 9, 25),
        ends_on=date(2026, 11, 1),
        open_dates=[date(2026, 9, 25), date(2026, 9, 26)] + _oct(2, 3, 4, 9, 10, 11, 15, 16, 17, 18, 22, 23, 24, 25, 28, 29, 30, 31)
        + [date(2026, 11, 1)],
        schedule="Select nights Sep 25 – Nov 1, 7–10pm.",
        price=None,
        scare_level="scary",
        ages=None,
        note="A haunted hayride in its 36th year, plus a haunted house and a pirate-ship haunt.",
    ),
    dict(
        kind="hayride",
        name="Sleepy Hollow Haunted Acres",
        venue="Gunser family farm",
        address="881 Highland Road, Newtown, PA 18940",
        town="Newtown",
        latitude=40.27245,
        longitude=-74.91079,
        url="https://www.sleepyhollowhayride.com/",
        ticket_url="https://www.sleepyhollowhayride.com/dates-and-prices",
        starts_on=date(2026, 9, 26),
        ends_on=date(2026, 10, 31),
        open_dates=[date(2026, 9, 26)] + _oct(2, 3, 4, 9, 10, 11, 16, 17, 18, 23, 24, 25, 30, 31),
        schedule="Fifteen nights, Friday to Sunday; entry 6:30–9:30pm (last hayride 9pm Sundays).",
        price="$45 for all three attractions, $22 for one; $5 more on Oct 10, 17 and 24.",
        scare_level="scary",
        ages=None,
        note="A haunted hayride, a haunted house and a field of frights on a 230-acre farm; often sells out, so buy online.",
    ),
    dict(
        kind="hayride",
        name="The Bates Motel & Haunted Hayride",
        venue="Arasapha Farm",
        address="1835 N Middletown Road, Glen Mills, PA 19342",
        town="Glen Mills",
        latitude=39.94366,
        longitude=-75.4951,
        url="https://thebatesmotel.com/",
        ticket_url="https://thebatesmotel.com/hours/",
        starts_on=date(2026, 9, 25),
        ends_on=date(2026, 11, 1),
        open_dates=[date(2026, 9, 25), date(2026, 9, 26)] + _oct(2, 3, 4) + [date(2026, 10, 9) + timedelta(days=i) for i in range(24)],
        schedule="Nightly from Oct 9 to Nov 1 (plus late-September and early-October weekends); 6:30–9pm Sunday to Thursday, 6:30–10pm Friday and Saturday.",
        price=None,
        scare_level="scary",
        ages=None,
        note="A haunted motel, a haunted hayride and a scarecrow trail on a working farm.",
    ),
    dict(
        kind="festival",
        name="Harvest Hayride",
        venue="Arasapha Farm",
        address="1835 N Middletown Road, Glen Mills, PA 19342",
        town="Glen Mills",
        latitude=39.94366,
        longitude=-75.4951,
        url="https://harvesthayride.com/",
        ticket_url=None,
        starts_on=date(2026, 9, 19),
        ends_on=date(2026, 11, 1),
        open_dates=_weekdays(date(2026, 9, 19), date(2026, 11, 1), {5, 6}),
        schedule="Saturdays and Sundays, Sep 19 – Nov 1, 10am–4pm (last pumpkin hayride 3pm).",
        price=None,
        scare_level="family",
        ages="The daytime, not-scary side of the Bates Motel farm.",
        note="Hayrides to the pumpkin patch, a corn maze, games and a playground.",
    ),
    dict(
        kind="hayride",
        name="Night Chills Haunted Hayride",
        venue="Winding Brook Farm",
        address="3014 Bristol Road, Warrington, PA 18976",
        town="Warrington",
        latitude=40.26455,
        longitude=-75.15489,
        url="https://www.windingbrookfarm.com/night-chills-haunted-hayride",
        ticket_url="https://www.windingbrookfarm.com/night-chills-haunted-hayride",
        starts_on=date(2026, 9, 25),
        ends_on=date(2026, 10, 30),
        open_dates=[date(2026, 9, 25), date(2026, 9, 26)] + _oct(2, 3, 9, 10, 16, 17, 18, 23, 24, 25, 29, 30),
        schedule="Select nights to Oct 30; 7:30–10pm Friday and Saturday, 7:30–9pm Sunday and Thursday.",
        price="$25 hayride; $45 with the Corn Walk of Horror and Haunted Hay Maze.",
        scare_level="scary",
        ages="The farm says it's not for young children.",
        note="A haunted hayride through the woods; the farm runs daytime family hayrides and a hay maze too.",
    ),
]


_GUIDES = [
    (
        "Pennsylvania Haunted Houses, Rated",
        "The Scare Factor",
        "https://www.thescarefactor.com/haunted-houses/pennsylvania/",
        "The Philadelphia side, from Eastern State Penitentiary's Halloween Nights to Bucks County hayrides, with scare ratings.",
        70,
    ),
    (
        "Home Haunts In and Around Cherry Hill",
        "FrightMaps",
        "https://frightmaps.com/haunted-houses/new-jersey/cherry-hill",
        "Decorated yards and home haunts posted by the people who build them, with nearby towns listed too.",
        80,
    ),
]

_guides = sa.table(
    "seasonal_guides",
    sa.column("id", sa.String),
    sa.column("season", sa.String),
    sa.column("title", sa.Text),
    sa.column("publisher", sa.Text),
    sa.column("url", sa.Text),
    sa.column("note", sa.Text),
    sa.column("starts_on", sa.Date),
    sa.column("ends_on", sa.Date),
    sa.column("sort_order", sa.Integer),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    table = op.create_table(
        "seasonal_attractions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("season", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("town", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("ticket_url", sa.Text(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("open_dates", postgresql.ARRAY(sa.Date()), nullable=True),
        sa.Column("schedule", sa.Text(), nullable=True),
        sa.Column("price", sa.Text(), nullable=True),
        sa.Column("scare_level", sa.String(20), nullable=True),
        sa.Column("ages", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("verified_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_seasonal_attractions_season", "seasonal_attractions", ["season"])
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        table,
        [
            {
                "id": str(uuid.uuid4()),
                "season": "halloween",
                "ticket_url": None,
                "source_url": None,
                "verified_on": _CHECKED,
                "created_at": now,
                "updated_at": now,
                **row,
            }
            for row in _SEED
        ],
    )
    op.bulk_insert(
        _guides,
        [
            {
                "id": str(uuid.uuid4()),
                "season": "halloween",
                "title": title,
                "publisher": publisher,
                "url": url,
                "note": note,
                "starts_on": date(2026, 9, 25),
                "ends_on": date(2026, 11, 1),
                "sort_order": order,
                "created_at": now,
                "updated_at": now,
            }
            for title, publisher, url, note, order in _GUIDES
        ],
    )


def downgrade() -> None:
    op.execute(_guides.delete().where(_guides.c.url.in_([g[2] for g in _GUIDES])))
    op.drop_index("ix_seasonal_attractions_season", table_name="seasonal_attractions")
    op.drop_table("seasonal_attractions")
