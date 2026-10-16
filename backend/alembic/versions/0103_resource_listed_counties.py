"""resource_services.listed_in_counties: which counties' NJ 211 searches listed a service

Revision ID: 0103
Revises: 0102
Create Date: 2026-10-16 18:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resource_services",
        sa.Column("listed_in_counties", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_resource_services_listed_in_counties", "resource_services", ["listed_in_counties"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_resource_services_listed_in_counties", table_name="resource_services")
    op.drop_column("resource_services", "listed_in_counties")
