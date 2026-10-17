"""Localz provider portal: onboarding requests, memberships, change requests, change log, private addresses + the "Localz reviewer" role

Revision ID: 0106
Revises: 0105
Create Date: 2026-10-17 14:00:00

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0106"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEWER_ROLE = "Localz reviewer"
REVIEWER_PERMISSIONS = ("resources.view", "resources.manage")


def _ts(name: str, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _user_fk(name: str, ondelete: str = "SET NULL", nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.String(36), sa.ForeignKey("users.id", ondelete=ondelete), nullable=nullable)


def upgrade() -> None:
    text_array = postgresql.ARRAY(sa.Text())

    # New nullable / defaulted columns only: the previous release keeps
    # working on this schema.
    op.add_column("resource_services", sa.Column("address_kind", sa.String(20), nullable=True))
    op.add_column("resource_services", sa.Column("hours", postgresql.JSONB(), nullable=True))
    op.add_column("resource_services", sa.Column("week_hours", postgresql.JSONB(), nullable=True))
    op.add_column("resource_services", sa.Column("closure_starts_on", sa.Date(), nullable=True))
    op.add_column("resource_services", sa.Column("closure_ends_on", sa.Date(), nullable=True))
    op.add_column("resource_services", sa.Column("closure_note", sa.Text(), nullable=True))
    op.add_column("resource_services", sa.Column("cost_kind", sa.String(20), nullable=True))
    op.add_column("resource_services", sa.Column("provider_owned_fields", text_array, nullable=False, server_default="{}"))

    op.create_table(
        "resource_private_addresses",
        sa.Column("service_id", sa.String(36), sa.ForeignKey("resource_services.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        _ts("updated_at"),
    )
    op.execute("ALTER TABLE resource_private_addresses ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "resource_onboarding_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("origin", sa.String(20), nullable=False),
        _user_fk("user_id"),
        _user_fk("created_by_user_id"),
        sa.Column(
            "claimed_service_id", sa.String(36), sa.ForeignKey("resource_services.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("submission", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("private_address", sa.String(), nullable=True),
        sa.Column("contact_name", sa.String(200), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(40), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("checklist", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.String(40), nullable=True),
        sa.Column("fields_to_fix", text_array, nullable=False, server_default="{}"),
        _user_fk("reviewed_by_user_id"),
        _ts("reviewed_at", nullable=True),
        _ts("submitted_at", nullable=True),
        sa.Column("service_ids", text_array, nullable=False, server_default="{}"),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_resource_onboarding_requests_status", "resource_onboarding_requests", ["status"])
    op.create_index("ix_resource_onboarding_requests_user_id", "resource_onboarding_requests", ["user_id"])
    op.create_index("ix_resource_onboarding_requests_ip_hash", "resource_onboarding_requests", ["ip_hash"])
    op.create_index("ix_resource_onboarding_requests_submitted_at", "resource_onboarding_requests", ["submitted_at"])
    op.execute("ALTER TABLE resource_onboarding_requests ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "provider_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        _user_fk("user_id", ondelete="CASCADE", nullable=False),
        sa.Column("service_id", sa.String(36), sa.ForeignKey("resource_services.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "organization_id", sa.String(36), sa.ForeignKey("resource_organizations.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("role", sa.String(20), nullable=False, server_default="owner"),
        _ts("verified_at", nullable=True),
        _user_fk("verified_by_user_id"),
        sa.Column(
            "request_id", sa.String(36), sa.ForeignKey("resource_onboarding_requests.id", ondelete="SET NULL"), nullable=True
        ),
        _ts("created_at"),
        sa.UniqueConstraint("user_id", "service_id", name="uq_provider_memberships_user_service"),
    )
    op.create_index("ix_provider_memberships_user_id", "provider_memberships", ["user_id"])
    op.create_index("ix_provider_memberships_service_id", "provider_memberships", ["service_id"])
    op.execute("ALTER TABLE provider_memberships ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "resource_change_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("service_id", sa.String(36), sa.ForeignKey("resource_services.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        _user_fk("user_id"),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("private_address", sa.String(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        _user_fk("reviewed_by_user_id"),
        _ts("reviewed_at", nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_resource_change_requests_service_id", "resource_change_requests", ["service_id"])
    op.create_index("ix_resource_change_requests_user_id", "resource_change_requests", ["user_id"])
    op.create_index("ix_resource_change_requests_status", "resource_change_requests", ["status"])
    op.execute("ALTER TABLE resource_change_requests ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "resource_change_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("service_id", sa.String(36), sa.ForeignKey("resource_services.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "request_id", sa.String(36), sa.ForeignKey("resource_onboarding_requests.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "change_request_id", sa.String(36), sa.ForeignKey("resource_change_requests.id", ondelete="SET NULL"), nullable=True
        ),
        _user_fk("actor_user_id"),
        sa.Column("actor_kind", sa.String(20), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("after", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("note", sa.Text(), nullable=True),
        _ts("reverted_at", nullable=True),
        _user_fk("reverted_by_user_id"),
        _ts("created_at"),
    )
    op.create_index("ix_resource_change_log_service_id", "resource_change_log", ["service_id"])
    op.create_index("ix_resource_change_log_request_id", "resource_change_log", ["request_id"])
    op.create_index("ix_resource_change_log_created_at", "resource_change_log", ["created_at"])
    op.execute("ALTER TABLE resource_change_log ENABLE ROW LEVEL SECURITY")

    # The reviewer role, only if there isn't one by that name yet (a super
    # admin may already have made it, or renamed its permissions).
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM roles WHERE name = :name"), {"name": REVIEWER_ROLE}).first():
        return
    role_id = str(uuid.uuid4())
    conn.execute(
        sa.text("INSERT INTO roles (id, name, description, created_at) VALUES (:id, :name, :description, now())"),
        {
            "id": role_id,
            "name": REVIEWER_ROLE,
            "description": "Reviews Localz provider listings: onboarding, change requests, verification, merges.",
        },
    )
    for permission in REVIEWER_PERMISSIONS:
        conn.execute(
            sa.text("INSERT INTO role_permissions (role_id, permission) VALUES (:role_id, :permission)"),
            {"role_id": role_id, "permission": permission},
        )


def downgrade() -> None:
    op.drop_table("resource_change_log")
    op.drop_table("resource_change_requests")
    op.drop_table("provider_memberships")
    op.drop_table("resource_onboarding_requests")
    op.drop_table("resource_private_addresses")
    for column in (
        "provider_owned_fields", "cost_kind", "closure_note", "closure_ends_on", "closure_starts_on",
        "week_hours", "hours", "address_kind",
    ):
        op.drop_column("resource_services", column)
    op.execute(
        sa.text("DELETE FROM roles WHERE name = :name").bindparams(name=REVIEWER_ROLE)
    )
