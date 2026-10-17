"""Outbound email: the outbox, verify-by-email codes, the 90-day check-in

Revision ID: 0111
Revises: 0110
Create Date: 2026-10-18 00:00:00

- outbound_emails (services/mailer.py): address and body encrypted while
  queued, erased once sent.
- provider_memberships: the source-published address a code may go to, and
  the code's hash, expiry and tries.
- resource_services.checkin_sent_on for the "Is this still right?" email.
- Seeds the email.outbox (hourly) and resources.provider_checkin (weekly)
  jobs if there aren't any.
"""
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0111"
down_revision: str | None = "0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOBS = (
    ("email.outbox", "Send waiting email", "Retries outbound email that didn't send right away and erases old rows.", "7 * * * *", {}),
    (
        "resources.provider_checkin",
        "Localz: is your listing still right?",
        "Emails Localz providers whose listing hasn't been confirmed in 90 days (at most every 30 days).",
        "13 10 * * 1",
        {"stale_days": 90, "remind_every_days": 30},
    ),
)


def upgrade() -> None:
    op.create_table(
        "outbound_emails",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("ref", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("to_address", sa.String(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbound_emails_ref", "outbound_emails", ["ref"])
    op.create_index("ix_outbound_emails_user_id", "outbound_emails", ["user_id"])
    op.create_index("ix_outbound_emails_created_at", "outbound_emails", ["created_at"])
    op.add_column("provider_memberships", sa.Column("verify_email", sa.Text(), nullable=True))
    op.add_column("provider_memberships", sa.Column("code_hash", sa.String(length=64), nullable=True))
    op.add_column("provider_memberships", sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("provider_memberships", sa.Column("code_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("resource_services", sa.Column("checkin_sent_on", sa.Date(), nullable=True))

    conn = op.get_bind()
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
    for kind, name, description, cron, params in JOBS:
        if conn.execute(sa.text("SELECT 1 FROM scheduled_jobs WHERE kind = :k LIMIT 1"), {"k": kind}).first():
            continue
        op.execute(
            job.insert().values(
                id=str(uuid.uuid4()), kind=kind, name=name, description=description, cron_expr=cron,
                timezone="America/New_York", params=json.loads(json.dumps(params)), enabled=True, run_once=False,
                created_at=sa.func.now(), updated_at=sa.func.now(),
            )
        )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_jobs WHERE kind IN ('email.outbox', 'resources.provider_checkin')")
    op.drop_column("resource_services", "checkin_sent_on")
    for column in ("code_attempts", "code_expires_at", "code_hash", "verify_email"):
        op.drop_column("provider_memberships", column)
    op.drop_table("outbound_emails")
