"""community resources for Localz (resource_organizations, resource_services) + the resources.refresh job

Revision ID: 0102
Revises: 0101
Create Date: 2026-10-16 12:00:00

"""
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0102"
down_revision: str | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False, unique=True),
        sa.Column("alternate_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("ALTER TABLE resource_organizations ENABLE ROW LEVEL SECURITY")

    text_array = postgresql.ARRAY(sa.Text())
    op.create_table(
        "resource_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("resource_organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("organization_name", sa.Text(), nullable=True),
        sa.Column("location_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("hours_text", sa.Text(), nullable=True),
        sa.Column("eligibility_text", sa.Text(), nullable=True),
        sa.Column("application_process", sa.Text(), nullable=True),
        sa.Column("fees", sa.Text(), nullable=True),
        sa.Column("required_documents", text_array, nullable=False, server_default="{}"),
        sa.Column("languages", text_array, nullable=False, server_default="{}"),
        sa.Column("accessibility", sa.Text(), nullable=True),
        sa.Column("transportation", sa.Text(), nullable=True),
        sa.Column("service_areas", text_array, nullable=False, server_default="{}"),
        sa.Column("taxonomy_codes", text_array, nullable=False, server_default="{}"),
        sa.Column("taxonomy_names", text_array, nullable=False, server_default="{}"),
        sa.Column("categories", text_array, nullable=False, server_default="{}"),
        sa.Column("alert", sa.Text(), nullable=True),
        sa.Column("last_assured_on", sa.Date(), nullable=True),
        sa.Column("missing_core", text_array, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("summary_hash", sa.String(64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("detail_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missed_crawls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "source_record_id", name="uq_resource_services_source_record"),
    )
    op.create_index("ix_resource_services_organization_id", "resource_services", ["organization_id"])
    op.create_index("ix_resource_services_categories", "resource_services", ["categories"], postgresql_using="gin")
    op.create_index("ix_resource_services_service_areas", "resource_services", ["service_areas"], postgresql_using="gin")
    op.create_index("ix_resource_services_status", "resource_services", ["status"])
    op.execute("ALTER TABLE resource_services ENABLE ROW LEVEL SECURITY")

    # The refresh job, only if there isn't one yet. Imported rather than
    # copied so the seeded params and the kind's defaults can't drift.
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM scheduled_jobs WHERE kind = 'resources.refresh' LIMIT 1")).first():
        return
    from scheduler.jobs.resources_refresh import DEFAULT_PARAMS

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
            kind="resources.refresh",
            name="Community resources refresh",
            description="Localz resources from NJ 211's public directory - polite crawl (robots.txt, 10 s between requests).",
            cron_expr="23 3 * * *",
            timezone="America/New_York",
            params=json.loads(json.dumps(DEFAULT_PARAMS)),
            enabled=True,
            run_once=False,
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_jobs WHERE kind = 'resources.refresh'")
    op.drop_table("resource_services")
    op.drop_table("resource_organizations")
