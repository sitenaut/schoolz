"""seasonal + localz: From We Can't to We Can's Christmas toy drive

The owner asked for "Give a Toy, Make a Christmas", a holiday appeal shared
in a Cherry Hill community group by From We Can't to We Can, a Vineland
501(c)(3) for children with disabilities and their families. The gifts go
to the children at its Christmas Social on Sunday Dec 13 at Masso's Orchard
Garden in Glassboro, each from the child's own wish list. Families apply to
come, so the Social itself is not listed as an event.

- A card in both season pages' "Volunteer & give back" group, like 0143's
  gift drives. You give by mail or online (its Donate page, its Amazon
  charity list, a check), so there is nowhere to go: the card has no
  position, and the season page shows no Directions for it.
- A Localz listing for the help families get from it (0145's rule: every
  volunteer place is also a listing): pediatric medical equipment free of
  charge through its Resource Recycler program, help with medical bills and
  other costs, and its member events, the Christmas Social among them. It
  has no office, only a P.O. box, so the listing has no address, and it
  serves "New Jersey", the only area its site names.

Facts are from its own pages and forms (wecant2wecan.org, read by plain
code with schoolz's User-Agent, which its robots.txt allows), its 2025
annual report, and its 501(c)(3) record (EIN 83-1089467), checked
2026-11-06. Its Amazon list refuses automated reads, so what is on it isn't
described. Only its general contacts are copied.

Only what's missing is added: a card with the same season and name, or a
listing whose source and key already exist, is left as it is.

Revision ID: 0148
Revises: 0147
Create Date: 2026-11-06 19:00:00
"""
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0148"
down_revision: str | None = "0147"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKED = date(2026, 11, 6)
SOURCE = "localz"
ORG = "From We Can't to We Can"
_NAME = "From We Can't to We Can's Give a Toy, Make a Christmas"
_LISTING_KEY = "wecant2wecan-families"


def _card(season: str, ends: date) -> dict:
    return dict(
        season=season,
        kind="volunteer",
        name=_NAME,
        venue=None,
        # Where checks go. There is no place to visit, so no position.
        address="P.O. Box 55, Vineland, NJ 08362",
        town="Vineland",
        latitude=None,
        longitude=None,
        url="https://www.wecant2wecan.org/donate",
        ticket_url=None,
        starts_on=date(2026, 11, 6),
        ends_on=ends,
        open_dates=None,
        schedule="Give now: the gifts go to the children at its Christmas Social on Sun Dec 13 in Glassboro.",
        price="Whatever you give: money on its Donate page, something from its Amazon charity list (shipped straight to it), or a check to P.O. Box 55, Vineland, NJ 08362.",
        ages="Any age can give.",
        note=(
            "A Vineland nonprofit for children with disabilities and their families gives every child at its Christmas "
            "Social presents from their own wish list, more than 1,000 toys last year, and your gifts pay for them. "
            "Families apply to come."
        ),
        source_url="https://www.wecant2wecan.org/events",
    )


_ATTRACTIONS = [
    _card("fall", date(2026, 11, 29)),
    _card("winter", date(2026, 12, 12)),
]

# Localz service types: taxonomy code, its name (NJ 211's own), and the
# Localz categories resources/categories.py gives it.
_TYPES = {
    "medical_equipment": ("LH-5000.2500", "General Medical Equipment/Supplies Provision", ("health",)),
    "holiday_gifts": ("PH-2950.3200", "Holiday Gifts/Toys", ("everyday-needs",)),
}

_LISTING = {
    "source_record_id": _LISTING_KEY,
    "organization_name": ORG,
    "location_name": ORG,
    "name": "Medical equipment and holiday help for children with disabilities",
    "types": ["medical_equipment", "holiday_gifts"],
    "description": (
        "A Vineland nonprofit for children with disabilities and their families. Its Resource Recycler program gives "
        "pediatric medical equipment free when insurance has denied it or a family can't afford it: "
        "wheelchairs, walkers, standers, shower chairs and more, which it delivers. It also helps "
        "with medical bills and other costs, and holds inclusive events for members. At its Christmas Social each "
        "child gets presents from their own wish list, paid for by its Give a Toy, Make a Christmas appeal."
    ),
    "address": None,
    "city": None,
    "postal_code": None,
    "latitude": None,
    "longitude": None,
    "phone": "856-202-3955",
    "email": "contact@wecant2wecan.org",
    "website": "https://www.wecant2wecan.org/programs",
    "hours_text": "No office or walk-in hours: ask by its online forms, by phone or by email.",
    "eligibility_text": (
        "Children with disabilities and their families. Medical equipment is for a family whose insurance denied it "
        "or keeps it waiting, or who can't afford it. Events are for members, who join with its annual membership form."
    ),
    "application_process": (
        "For equipment, fill out the Medical Equipment Inquiry form on its Programs page. For help with medical bills "
        "or other costs, use the help form on its Contact page. Members apply for each event, the Christmas Social "
        "(Dec 13, Glassboro) included; it fills up early and approval isn't guaranteed."
    ),
    "fees": "Free.",
    "cost_kind": "free",
    "service_areas": ["New Jersey"],
    "ways_to_help": {
        "volunteer_roles": ["Help at its events"],
        "volunteer_how": "Sign up for its events on South Jersey Volunteers, or mail encouragement cards for its children to P.O. Box 55, Vineland, NJ 08362.",
        "volunteer_url": "https://sjvolunteers.galaxydigital.com/agency/detail/?agency_id=164275",
        "donations": ["Money for its Christmas Social gifts and programs", "Gently used pediatric medical equipment"],
        "wishlist_url": "https://www.amazon.com/hz/wishlist/ls/4F7YQ65RV87K",
    },
}

# Each season card's listing, as in 0145.
_CARD_LISTINGS = {_NAME: _LISTING_KEY}


def categories(types: list[str]) -> list[str]:
    """In resources/categories.py's nav order."""
    nav = ("food", "english", "housing-bills", "health", "kids-family", "money-work", "legal-safety", "everyday-needs")
    wanted = {c for t in types for c in _TYPES[t][2]}
    return [c for c in nav if c in wanted]


def missing_core(row: dict) -> list[str]:
    """resources/refresh.py's required core."""
    checks = {
        "name": row.get("name"),
        "address": row.get("address") or row.get("service_areas"),
        "hours": row.get("hours_text"),
        "phone": row.get("phone"),
        "services": row.get("types"),
    }
    return [field for field, value in checks.items() if not value]


_attractions = sa.table(
    "seasonal_attractions",
    *[sa.column(c) for c in ("id", "season", "kind", "name", "venue", "address", "town", "latitude", "longitude", "url", "ticket_url")],
    sa.column("starts_on", sa.Date()),
    sa.column("ends_on", sa.Date()),
    sa.column("open_dates", sa.ARRAY(sa.Date())),
    *[sa.column(c) for c in ("schedule", "price", "scare_level", "ages", "note", "source_url", "resource_id")],
    sa.column("verified_on", sa.Date()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_services = sa.table(
    "resource_services",
    *[sa.column(c) for c in ("id", "organization_id", "source", "source_record_id", "name", "organization_name", "location_name",
                             "description", "phone", "email", "website", "address", "city", "postal_code", "hours_text",
                             "eligibility_text", "application_process", "fees", "status", "address_kind", "cost_kind")],
    sa.column("latitude", sa.Float()),
    sa.column("longitude", sa.Float()),
    *[sa.column(c, sa.ARRAY(sa.Text())) for c in ("service_areas", "taxonomy_codes", "taxonomy_names", "categories", "missing_core")],
    sa.column("ways_to_help", JSONB()),
    sa.column("last_assured_on", sa.Date()),
    sa.column("first_seen_at", sa.DateTime(timezone=True)),
    sa.column("last_seen_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_orgs = sa.table(
    "resource_organizations",
    *[sa.column(c) for c in ("id", "name", "name_key", "url")],
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def name_key(name: str) -> str:
    """resources/refresh.py's organization key."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(UTC)
    s, a = _services.c, _attractions.c

    listing_id = conn.execute(sa.select(s.id).where(s.source == SOURCE, s.source_record_id == _LISTING_KEY)).scalar()
    if listing_id is None:
        org_id = conn.execute(sa.select(_orgs.c.id).where(_orgs.c.name_key == name_key(ORG))).scalar()
        if org_id is None:
            org_id = str(uuid.uuid4())
            conn.execute(_orgs.insert().values(id=org_id, name=ORG, name_key=name_key(ORG), url="https://www.wecant2wecan.org/", created_at=now, updated_at=now))
        listing_id = str(uuid.uuid4())
        types = _LISTING["types"]
        conn.execute(
            _services.insert().values(
                id=listing_id,
                organization_id=org_id,
                source=SOURCE,
                status="active",
                address_kind=None,
                taxonomy_codes=[_TYPES[t][0] for t in types],
                taxonomy_names=[_TYPES[t][1] for t in types],
                categories=categories(types),
                missing_core=missing_core(_LISTING),
                last_assured_on=_CHECKED,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
                **{k: v for k, v in _LISTING.items() if k != "types"},
            )
        )

    have = {tuple(r) for r in conn.execute(sa.select(a.season, a.name))}
    rows = [
        {"id": str(uuid.uuid4()), "scare_level": None, "resource_id": listing_id, "verified_on": _CHECKED, "created_at": now, "updated_at": now, **row}
        for row in _ATTRACTIONS
        if (row["season"], row["name"]) not in have
    ]
    if rows:
        op.bulk_insert(_attractions, rows)


def downgrade() -> None:
    s, a = _services.c, _attractions.c
    op.execute(_attractions.delete().where(a.name == _NAME, a.season.in_([row["season"] for row in _ATTRACTIONS])))
    op.execute(_services.delete().where(s.source == SOURCE, s.source_record_id == _LISTING_KEY))
