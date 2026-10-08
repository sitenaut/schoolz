"""seasonal_guides - links to other people's seasonal guides (the 🎃 badge)

Seeds fall 2026 from I'm a South Jersey Mom: her Halloween house map and
three fall guides through Nov 1 (🎃), then her fall roundup through
Thanksgiving weekend (🍂). Links and our own one-line notes only - see
models.SeasonalGuide for why we never copy the listings themselves.

Revision ID: 0081
Revises: 0080
Create Date: 2026-10-08 12:00:00

"""
import uuid
from datetime import date, datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0081"
down_revision: Union[str, None] = "0080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SITE = "https://www.imasouthjerseymom.net"
_PUBLISHER = "I'm a South Jersey Mom"
_FESTIVALS = f"{_SITE}/seasonal/3327078_south-jersey-fall-festivals-2026"
_PUMPKINS = f"{_SITE}/seasonal/3334297_2026-south-jersey-pumpkin-picking-hayrides-fall-farm-fun"
# (season, title, url, note, starts_on, ends_on, sort_order). Halloween ends on Halloween weekend's Sunday; from
# Nov 2 the badge turns to fall (🍂) through Thanksgiving weekend, so winter can start without the two overlapping.
_SEED = [
    (
        "halloween",
        "2026 South Jersey Halloween House Map",
        f"{_SITE}/seasonal/3337877_2026-south-jersey-halloween-house-map",
        "Decorated houses, walk-throughs and drive-bys across South Jersey, added by the homeowners themselves.",
        date(2026, 9, 25),
        date(2026, 11, 1),
        0,
    ),
    ("halloween", "South Jersey Fall Festivals 2026", _FESTIVALS, "Fall festivals around the region, with dates.", date(2026, 9, 1), date(2026, 11, 1), 10),
    ("halloween", "Pumpkin Picking, Hayrides & Fall Farm Fun", _PUMPKINS, "Farms for pumpkin picking, hayrides and corn mazes.", date(2026, 9, 1), date(2026, 11, 1), 20),
    (
        "halloween",
        "The Great Pumpkin Glow at Dalton Farms",
        f"{_SITE}/seasonal/3348815_the-great-pumpkin-glow-at-dalton-farms-south-jersey-fall-2026",
        "An evening pumpkin light display at a local farm.",
        date(2026, 9, 25),
        date(2026, 11, 1),
        30,
    ),
    ("fall", "Fall in South Jersey", f"{_SITE}/seasonal/fall", "Her fall roundup: festivals, farms and seasonal outings.", date(2026, 11, 2), date(2026, 11, 29), 0),
    ("fall", "South Jersey Fall Festivals 2026", _FESTIVALS, "The festivals still running into November.", date(2026, 11, 2), date(2026, 11, 15), 10),
]


def upgrade() -> None:
    table = op.create_table(
        "seasonal_guides",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("season", sa.String(40), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_seasonal_guides_season", "seasonal_guides", ["season"])
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        table,
        [
            {
                "id": str(uuid.uuid4()),
                "season": season,
                "title": title,
                "publisher": _PUBLISHER,
                "url": url,
                "note": note,
                "starts_on": starts,
                "ends_on": ends,
                "sort_order": order,
                "created_at": now,
                "updated_at": now,
            }
            for season, title, url, note, starts, ends, order in _SEED
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_seasonal_guides_season", table_name="seasonal_guides")
    op.drop_table("seasonal_guides")
