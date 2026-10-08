"""prerender_warm job - render every sitemap page for crawlers nightly

Revision ID: 0083
Revises: 0082
Create Date: 2026-10-08 14:00:00

So Googlebot is served a stored snapshot instead of waiting on a live render
(see scheduler/jobs/prerender_warm.py). 22:40 ET: clear of the 1-2 AM DST
hour and of the 3-5 AM daily menu scans.
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0083"
down_revision: Union[str, None] = "0082"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME = "Prerender warm (crawler snapshots)"


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
            kind="prerender.warm",
            name=NAME,
            description="Render every sitemap page into the crawler snapshot cache so search engines never wait on a live render. Skips pages rendered in the last 18h.",
            cron_expr="40 22 * * *",
            timezone="America/New_York",
            params={},
            enabled=True,
            run_once=False,
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM scheduled_jobs WHERE name = '{NAME}'")
