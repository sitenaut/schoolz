"""the resources.childcarenj job: Localz child care providers from ChildCareNJ.gov

Revision ID: 0105
Revises: 0104
Create Date: 2026-10-17 10:00:00

"""
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0105"
down_revision: str | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Only if there isn't one yet. Imported rather than copied so the seeded
    # params and the kind's defaults can't drift.
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM scheduled_jobs WHERE kind = 'resources.childcarenj' LIMIT 1")).first():
        return
    from scheduler.jobs.resources_childcare import DEFAULT_PARAMS

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
            kind="resources.childcarenj",
            name="Child care providers refresh",
            description="Localz child care providers from ChildCareNJ.gov - one request per county, 5 s apart.",
            cron_expr="41 4 * * 2",
            timezone="America/New_York",
            params=json.loads(json.dumps(DEFAULT_PARAMS)),
            enabled=True,
            run_once=False,
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_jobs WHERE kind = 'resources.childcarenj'")
