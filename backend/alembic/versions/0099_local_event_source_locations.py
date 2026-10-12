"""Local events: say where the feeds that never state a venue are

Some feeds publish no address at all - a township calendar, a library
branch's own page - so local_events/locate.py has nothing to geocode and
their events would show at every radius on /local. Each gets the `location`
param (town level is enough for a radius in miles), which is only used when
an event's own address and venue name can't be found. Only sources that exist
and have no `location` yet are touched, in whichever job lists them.

Revision ID: 0099
Revises: 0098
Create Date: 2026-10-11 23:10:00

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0099"
down_revision: Union[str, None] = "0098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCATIONS = {
    "evesham_township": "Marlton, NJ",
    "clementon_township": "Clementon, NJ",
    "merchantville": "Merchantville, NJ",
    "Cherry Hill Township Events": "Cherry Hill, NJ",
    "ccls_bellmawr": "Bellmawr, NJ",
    "ccls_downtown_camden": "Camden, NJ",
    "ccls_ferry_avenue": "Camden, NJ",
    "ccls_gloucester_township": "Blackwood, NJ",
    "ccls_haddon_township": "Westmont, NJ",
    "ccls_merchantville": "Merchantville, NJ",
    "ccls_south_county": "Atco, NJ",
    "ccls_voorhees": "Voorhees, NJ",
    "pennsauken_library": "Pennsauken, NJ",
    "runnemede_library": "Runnemede, NJ",
    "collingswood_library": "Collingswood, NJ",
    "barrington_library": "Barrington, NJ",
    "grand_theater_williamstown": "Williamstown, NJ",
    "voorhees_theatre_company": "Voorhees, NJ",
    "wxpn_concerts": "Philadelphia, PA",
    # Feeds whose "address" is a room ("Conference Center, Lower Level").
    "Cherry Hill Public Library": "1100 Kings Highway North, Cherry Hill, NJ 08034",
    "shop_haddon": "Westmont, NJ",
    "smoke_and_mirrors_magic_theater": "Huntingdon Valley, PA",
}


def _each_entry(params: dict):
    for value in params.values():
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict) and entry.get("name") in LOCATIONS:
                    yield entry


def _rewrite(change) -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, params FROM scheduled_jobs WHERE kind = 'local_events.refresh'")).fetchall()
    for row in rows:
        params = row.params if isinstance(row.params, dict) else json.loads(row.params or "{}")
        if not isinstance(params, dict):
            continue
        changed = [change(entry) for entry in _each_entry(params)]
        if any(changed):
            conn.execute(
                sa.text("UPDATE scheduled_jobs SET params = :p, updated_at = now() WHERE id = :id"),
                {"p": json.dumps(params), "id": row.id},
            )


def upgrade() -> None:
    def add(entry: dict) -> bool:
        if entry.get("location"):
            return False
        entry["location"] = LOCATIONS[entry["name"]]
        return True

    _rewrite(add)


def downgrade() -> None:
    def drop(entry: dict) -> bool:
        if entry.get("location") != LOCATIONS[entry["name"]]:
            return False
        del entry["location"]
        return True

    _rewrite(drop)
