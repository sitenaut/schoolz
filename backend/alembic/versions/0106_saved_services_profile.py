"""Localz saved services profile: consent_records and services_profiles

Revision ID: 0106
Revises: 0105
Create Date: 2026-10-17 14:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0106"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consent_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_consent_records_user_id", "consent_records", ["user_id"])
    op.create_table(
        "services_profiles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        # Encrypted JSON (crypto.EncryptedText, purpose "services_profile").
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alerts_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("alert_frequency", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("services_profiles")
    op.drop_index("ix_consent_records_user_id", table_name="consent_records")
    op.drop_table("consent_records")
