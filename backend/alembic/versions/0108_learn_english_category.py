"""Localz "Learn English" category: tag the listings already stored

Revision ID: 0108
Revises: 0107
Create Date: 2026-10-17 15:00:00

New and changed records get it from refresh._derive; unchanged ones are
never re-derived, so they're tagged here once. Only adds the tag - nothing
else about a row changes. Imported rather than copied so the rule can't
drift from resources/categories.py.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0108"
down_revision: str | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from resources.categories import CATEGORIES, categories_for

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, taxonomy_codes, name, description, categories FROM resource_services WHERE NOT ('english' = ANY(categories))")
    ).all()
    update = sa.text("UPDATE resource_services SET categories = :categories WHERE id = :id")
    for row in rows:
        if "english" not in categories_for(list(row.taxonomy_codes or []), row.name, row.description):
            continue
        have = set(row.categories or []) | {"english"}
        conn.execute(update, {"id": row.id, "categories": [k for k in CATEGORIES if k in have]})


def downgrade() -> None:
    op.execute("UPDATE resource_services SET categories = array_remove(categories, 'english')")
