"""seasonal_guides: link three haunted-attraction guides

Links only, like 0081. NewJerseyHauntedHouses.com's terms forbid reproducing
its listings or incorporating them into any information retrieval system, and
The Scare Factor reserves all rights and turns away scripted requests, so we
never scan either. Gloucester County is NJHH's South Jersey page with the most
attractions; The Scare Factor's NJ page adds haunts NJHH doesn't list. 13 Haunts
is a marketing group of ten big haunts, most around Philadelphia - too few to
be worth a scan.

Revision ID: 0084
Revises: 0083
Create Date: 2026-10-08 15:00:00

"""
import uuid
from datetime import date, datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0084"
down_revision: Union[str, None] = "0083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NJHH = "https://www.newjerseyhauntedhouses.com/county/gloucester.html"
_SCARE_FACTOR = "https://www.thescarefactor.com/haunted-houses/new-jersey/"
_13_HAUNTS = "https://www.13haunts.com/haunts/"
# (title, publisher, url, note, sort_order)
_SEED = [
    (
        "Haunted Houses, Hayrides & Corn Mazes",
        "NewJerseyHauntedHouses.com",
        _NJHH,
        "Haunted attractions, hayrides and corn mazes, starting with Gloucester County; browse other counties from there.",
        40,
    ),
    (
        "New Jersey Haunted Houses, Rated",
        "The Scare Factor",
        _SCARE_FACTOR,
        "Haunted houses and trails statewide with reviews and scare ratings, including several South Jersey haunts not in other guides.",
        50,
    ),
    (
        "Big Haunts Around Philadelphia",
        "13 Haunts",
        _13_HAUNTS,
        "A group of large haunts in the Philadelphia area, Pennsylvania, South Jersey and Delaware, with shared coupons.",
        60,
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
    now = datetime.now(timezone.utc)
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
            for title, publisher, url, note, order in _SEED
        ],
    )


def downgrade() -> None:
    op.execute(_guides.delete().where(_guides.c.url.in_([_NJHH, _SCARE_FACTOR, _13_HAUNTS])))
