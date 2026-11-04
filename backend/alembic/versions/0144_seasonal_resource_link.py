"""seasonal_attractions.resource_id: a volunteer place's Localz listing

Volunteers are what provide a soup kitchen's meals or a toy drive's gifts,
so each volunteer place on a season page can point at its Localz listing,
the help itself, and its card links there. Nullable: a park cleanup or a
wreath-laying has no one on the other side to list. 0145 fills it.

Revision ID: 0144
Revises: 0143
Create Date: 2026-11-04 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0144"
down_revision: str | None = "0143"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("seasonal_attractions", sa.Column("resource_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_seasonal_attractions_resource_id",
        "seasonal_attractions",
        "resource_services",
        ["resource_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_seasonal_attractions_resource_id", "seasonal_attractions", type_="foreignkey")
    op.drop_column("seasonal_attractions", "resource_id")
