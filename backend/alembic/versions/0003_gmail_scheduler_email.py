"""gmail tokens, scheduler, email scanners, smore blocks

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gmail_tokens",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("google_email", sa.String(length=255), primary_key=True),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=False),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("cron_expr", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="America/New_York"),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("last_duration_ms", sa.Integer(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "kind", "name", name="uq_scheduled_job_owner_kind_name"),
    )

    op.create_table(
        "job_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("scheduled_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("log_excerpt", sa.String(), nullable=True),
        sa.Column("triggered_by", sa.String(length=20), nullable=False, server_default="cron"),
    )
    op.create_index("ix_job_runs_job_id", "job_runs", ["job_id"])

    op.create_table(
        "email_scanners",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("google_email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("from_contains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("subject_contains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("body_contains", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("raw_query", sa.String(length=500), nullable=True),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("scheduled_job_id", sa.String(length=36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "email_scanner_matches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("scanner_id", sa.String(length=36), sa.ForeignKey("email_scanners.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.String(length=100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sender", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("snippet", sa.String(length=1000), nullable=True),
        sa.Column("processor_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("processor_error", sa.String(), nullable=True),
        sa.Column("artifact_kind", sa.String(length=50), nullable=True),
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scanner_id", "message_id", name="uq_email_scanner_matches_msg"),
    )

    op.create_table(
        "school_email_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scanner_id", sa.String(length=36), sa.ForeignKey("email_scanners.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=100), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("body_text", sa.String(), nullable=True),
        sa.Column("newsletter_links", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_school_email_messages_owner_user_id", "school_email_messages", ["owner_user_id"])

    op.create_table(
        "smore_newsletters",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("scheduled_job_id", sa.String(length=36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("url", name="uq_smore_newsletters_url"),
    )

    op.create_table(
        "smore_blocks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "newsletter_id",
            sa.String(length=36),
            sa.ForeignKey("smore_newsletters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=20), nullable=False),
        sa.Column("text_content", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(length=1000), nullable=True),
        sa.Column("link_url", sa.String(length=1000), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("pending_vision_extraction", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vision_extracted_text", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("newsletter_id", "content_hash", name="uq_smore_block_newsletter_hash"),
    )
    op.create_index("ix_smore_blocks_newsletter_id", "smore_blocks", ["newsletter_id"])


def downgrade() -> None:
    op.drop_table("smore_blocks")
    op.drop_table("smore_newsletters")
    op.drop_table("school_email_messages")
    op.drop_table("email_scanner_matches")
    op.drop_table("email_scanners")
    op.drop_table("job_runs")
    op.drop_table("scheduled_jobs")
    op.drop_table("gmail_tokens")
