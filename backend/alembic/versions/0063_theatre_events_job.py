"""Local events: a job for community theatre companies' own season pages.

Revision ID: 0063
Revises: 0062
Create Date: 2026-09-27 23:30:00

Its own job rather than more sources on the main refresh: each page can cost
a model call (unchanged pages are cached, so most runs cost nothing) and a
scraper render, and a season page changes far less often than a feed.
"""
import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0063"
down_revision: Union[str, None] = "0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME = "Local events refresh: community theatre"

PARAMS = json.loads(r"""
{
    "theatre_sources": [
        {
            "name": "haddonfield_plays_and_players",
            "venue_name": "Haddonfield Plays & Players",
            "venue_address": "957 Haddon Ave, Collingswood, NJ 08108",
            "urls": [
                "https://www.haddonfieldplayers.com/events",
                "https://www.haddonfieldplayers.com/2026-season"
            ]
        },
        {
            "name": "ritz_theatre_co",
            "venue_name": "Ritz Theatre Company",
            "venue_address": "915 White Horse Pike, Oaklyn, NJ 08107",
            "urls": [
                "https://ritztheatreco.org/2027-season/",
                "https://ritztheatreco.org/40th-anniversary-season/",
                "https://ritztheatreco.org/2026-ritz-kidz-season/",
                "https://ritztheatreco.org/2027-ritz-kidz-season/"
            ]
        },
        {
            "name": "voorhees_theatre_company",
            "venue_name": "Voorhees Theatre Company",
            "urls": [
                "https://www.voorheestheatre.org/our-shows",
                "https://www.voorheestheatre.org/fall-all-ages"
            ]
        },
        {
            "name": "moorestown_theater_company",
            "venue_name": "Moorestown Theater Company",
            "venue_address": "110 E Main St, Moorestown, NJ 08057",
            "urls": [
                "https://www.moorestowntheatercompany.org/calendar",
                "https://www.moorestowntheatercompany.org/newevents",
                "https://www.moorestowntheatercompany.org/holiday-26",
                "https://www.moorestowntheatercompany.org/2nd-stage-26"
            ]
        },
        {
            "name": "grand_theater_williamstown",
            "venue_name": "The Grand Theater (Road Company)",
            "urls": [
                "https://roadcompany.com/current-season.html",
                "https://roadcompany.com/2026-season-1.html",
                "https://roadcompany.com/2027-season.html"
            ]
        },
        {
            "name": "south_camden_theatre_co",
            "venue_name": "Waterfront South Theatre",
            "venue_address": "1810 Ferry Ave, Camden, NJ 08104",
            "urls": [
                "https://sctcnj.org/",
                "https://sctcnj.org/native-gardens/"
            ]
        },
        {
            "name": "masquerade_theatre",
            "venue_name": "Masquerade Theatre",
            "urls": [
                "https://www.masqueradetheatre.org/shows",
                "https://www.masqueradetheatre.org/show-experiences/2627season"
            ]
        },
        {
            "name": "haddonfield_theater_arts_center",
            "venue_name": "Haddonfield Theater Arts Center",
            "urls": [
                "https://haddonfieldtheaterartscenter.com/",
                "https://haddonfieldtheaterartscenter.com/schedule-%26-classes",
                "https://haddonfieldtheaterartscenter.com/company-program"
            ]
        },
        {
            "name": "rise_performing_arts",
            "venue_name": "Rise Performing Arts",
            "urls": [
                "https://www.riseperformingarts.com/",
                "https://www.riseperformingarts.com/event"
            ]
        },
        {
            "name": "bridge_players_theatre",
            "venue_name": "Bridge Players Theatre",
            "urls": [
                "https://bridgeplayerstheatre.com/",
                "https://bridgeplayerstheatre.com/special-events"
            ],
            "venue_address": "Burlington, NJ"
        },
        {
            "name": "broadway_theatre_of_pitman",
            "venue_name": "Broadway Theatre of Pitman",
            "venue_address": "43 S Broadway, Pitman, NJ 08071",
            "urls": [
                "https://www.thebroadwaytheatre.org/2026-mainstage-season/",
                "https://www.thebroadwaytheatre.org/2027-mainstage-season/",
                "https://www.thebroadwaytheatre.org/childrens-theatre/",
                "https://www.thebroadwaytheatre.org/2027-childrens-theatre/"
            ]
        },
        {
            "name": "mainstage_center_for_the_arts",
            "venue_name": "MainStage Center for the Arts",
            "urls": [
                "https://mainstage.org/mainstage-productions/",
                "https://mainstage.org/buy-tickets/"
            ]
        },
        {
            "name": "cherry_hill_pac",
            "venue_name": "Cherry Hill Performing Arts Center",
            "urls": [
                "https://www.cherryhillpac.com/student-showcase.html",
                "https://www.cherryhillpac.com/musical-theatre-troupe.html",
                "https://www.cherryhillpac.com/10th-anniversary.html"
            ]
        },
        {
            "name": "triple_threat_theater",
            "venue_name": "Triple Threat Theater Productions",
            "urls": [
                "https://www.triplethreattheaterproductions.com/",
                "https://www.triplethreattheaterproductions.com/fall2025theater.html"
            ]
        },
        {
            "name": "smoke_and_mirrors_magic_theater",
            "venue_name": "Smoke & Mirrors Magic Theater",
            "urls": [
                "https://smokeandmirrorstheater.com/"
            ],
            "default_categories": [
                "magic",
                "family"
            ]
        }
    ]
}
""")


def upgrade() -> None:
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM scheduled_jobs WHERE name = :n"), {"n": NAME}).first():
        return
    job = sa.table(
        "scheduled_jobs",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("cron_expr", sa.String),
        sa.column("timezone", sa.String),
        sa.column("params", sa.JSON),
        sa.column("enabled", sa.Boolean),
        sa.column("run_once", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        job.insert().values(
            id=str(uuid.uuid4()),
            kind="local_events.refresh",
            name=NAME,
            description="South Jersey community theatre seasons read from each company's own site (Haiku extracts the productions; Test fetch before editing).",
            cron_expr="23 6,18 * * *",
            timezone="America/New_York",
            params=PARAMS,
            enabled=True,
            run_once=False,
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM scheduled_jobs WHERE name = '{NAME}'")
