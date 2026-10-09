"""Cityside Pumpkin Patch at Liberty Point, Philadelphia

Facts are from the venue's own page (checked 2026-10-09). The venue posts
the season window but not daily hours or a price, so those stay null rather
than being taken from news snippets. Its tickets are sold only through a
third-party listing, so ticket_url points there.

Revision ID: 0089
Revises: 0088
Create Date: 2026-10-09 15:00:00

"""
import uuid
from datetime import date, datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0089"
down_revision: Union[str, None] = "0088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECKED = date(2026, 10, 9)
_NAME = "Cityside Pumpkin Patch"

_ROW = dict(
    kind="festival",
    name=_NAME,
    venue="Liberty Point",
    address="211 S. Christopher Columbus Blvd, Philadelphia, PA 19106",
    town="Philadelphia",
    latitude=39.9434,
    longitude=-75.1405,
    url="https://citysidepumpkinpatch.com/philly",
    ticket_url="https://bucketlisters.com/experience/cityside-pumpkin-patch",
    starts_on=date(2026, 10, 3),
    ends_on=date(2026, 11, 2),
    open_dates=None,
    schedule="Open Oct 3 – Nov 2. Check the ticket page for the day's hours.",
    price=None,
    scare_level="family",
    ages="Billed as family-friendly; children 3 and up need a ticket.",
    note="A rooftop pumpkin patch on the Delaware waterfront: pick your own pumpkin, pumpkin smashing, carnival games and photo backdrops.",
    source_url=None,
)

_table = sa.table(
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
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        _table,
        [{"id": str(uuid.uuid4()), "season": "halloween", "verified_on": _CHECKED, "created_at": now, "updated_at": now, **_ROW}],
    )


def downgrade() -> None:
    op.execute(_table.delete().where(_table.c.season == "halloween", _table.c.name == _NAME))
