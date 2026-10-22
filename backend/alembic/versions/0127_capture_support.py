"""Backpack Capture support: problem reports and a Tech support role

capture_diagnostics.reported_at marks an update the parent reported a problem
with from My family; contact_messages.capture_diagnostic_id ties the report in
the admins' Inbox to that update's log. Seeds a "Tech support" role (Inbox
plus support.view) if no role has that name yet; a super admin assigns it.
Additive: two nullable columns and one role row.

Revision ID: 0127
Revises: 0126
Create Date: 2026-10-22 00:00:00
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0127"
down_revision: str | None = "0126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_NAME = "Tech support"
ROLE_DESCRIPTION = "Helps parents when Backpack Capture goes wrong: their reports in the Inbox and the update logs."
ROLE_PERMISSIONS = ("inbox.manage", "support.view")


def upgrade() -> None:
    op.add_column("capture_diagnostics", sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "contact_messages",
        sa.Column(
            "capture_diagnostic_id",
            sa.String(36),
            sa.ForeignKey("capture_diagnostics.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM roles WHERE name = :n"), {"n": ROLE_NAME}).first():
        return
    role_id = str(uuid.uuid4())
    conn.execute(
        sa.text("INSERT INTO roles (id, name, description, created_at) VALUES (:id, :n, :d, now())"),
        {"id": role_id, "n": ROLE_NAME, "d": ROLE_DESCRIPTION},
    )
    for key in ROLE_PERMISSIONS:
        conn.execute(
            sa.text("INSERT INTO role_permissions (role_id, permission) VALUES (:r, :p)"), {"r": role_id, "p": key}
        )


def downgrade() -> None:
    op.drop_column("contact_messages", "capture_diagnostic_id")
    op.drop_column("capture_diagnostics", "reported_at")
