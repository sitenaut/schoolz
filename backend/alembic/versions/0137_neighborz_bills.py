"""Neighborz: bill_requests, bill_holds, bill_givers and the bills.sweep job

Revision ID: 0137
Revises: 0136
Create Date: 2026-10-28 00:00:00

docs/NEIGHBORZ_DESIGN.md. Account number, ZIP, extraction, image and
confirmation number are encrypted columns (crypto.EncryptedText). Partial
unique indexes: one live hold per bill, one active hold per giver. Seeds the
hourly bills.sweep job if there isn't one.
"""
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0137"
down_revision: str | None = "0136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB = (
    "bills.sweep",
    "Neighborz: holds, answers and erasing",
    "Ends 24-hour holds, closes unanswered and old bills, erases closed bills' account numbers, sends the reminders.",
    "23 * * * *",
    {},
)


def upgrade() -> None:
    op.create_table(
        "bill_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requester_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("utility", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("amount_due_cents", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("shutoff_notice", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("county", sa.String(40), nullable=True),
        sa.Column("avatar", sa.String(30), nullable=True),
        sa.Column("account_number", sa.String(), nullable=True),
        sa.Column("service_zip", sa.String(), nullable=True),
        sa.Column("account_fingerprint", sa.String(64), nullable=True),
        sa.Column("extraction", sa.String(), nullable=True),
        sa.Column("image", sa.String(), nullable=True),
        sa.Column("image_type", sa.String(40), nullable=True),
        sa.Column("image_sha256", sa.String(64), nullable=True),
        sa.Column("flags", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("refused", sa.String(30), nullable=True),
        sa.Column("reject_reason", sa.String(30), nullable=True),
        sa.Column("thanks", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_bill_requests_requester_id", "bill_requests", ["requester_id"])
    op.create_index("ix_bill_requests_status", "bill_requests", ["status"])
    op.create_index("ix_bill_requests_account_fingerprint", "bill_requests", ["account_fingerprint"])

    op.create_table(
        "bill_holds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("bill_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("giver_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_cents", sa.Integer(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("confirmation_number", sa.String(), nullable=True),
    )
    op.create_index("ix_bill_holds_request_id", "bill_holds", ["request_id"])
    op.create_index("ix_bill_holds_giver_id", "bill_holds", ["giver_id"])
    op.create_index(
        "uq_bill_holds_live_per_request", "bill_holds", ["request_id"], unique=True,
        postgresql_where=sa.text("status IN ('active', 'reported', 'disputed')"),
    )
    op.create_index(
        "uq_bill_holds_active_per_giver", "bill_holds", ["giver_id"], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "bill_givers",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("strikes_cleared_at", sa.DateTime(timezone=True), nullable=True),
    )

    conn = op.get_bind()
    kind, name, description, cron, params = JOB
    if not conn.execute(sa.text("SELECT 1 FROM scheduled_jobs WHERE kind = :k LIMIT 1"), {"k": kind}).first():
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
                id=str(uuid.uuid4()), kind=kind, name=name, description=description, cron_expr=cron,
                timezone="America/New_York", params=json.loads(json.dumps(params)), enabled=True, run_once=False,
                created_at=sa.func.now(), updated_at=sa.func.now(),
            )
        )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_jobs WHERE kind = 'bills.sweep'")
    op.drop_table("bill_givers")
    op.drop_index("uq_bill_holds_active_per_giver", table_name="bill_holds")
    op.drop_index("uq_bill_holds_live_per_request", table_name="bill_holds")
    op.drop_table("bill_holds")
    op.drop_table("bill_requests")
