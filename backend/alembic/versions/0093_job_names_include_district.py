"""School-level scan job names carry their district

`scheduled_jobs` is unique on (owner, kind, name) and school names repeat
across districts, so the second "Parkview Elementary School" could not get
its jobs. New jobs are named "<label>: <school> (<district>)"
(`scheduler/job_names.py`); this renames the existing ones to match, so an
admin's Jobs list reads the same for old and new rows.

Revision ID: 0093
Revises: 0092
Create Date: 2026-10-11 16:00:00

"""
from typing import Sequence, Union

from alembic import op

revision = "0093"
down_revision = "0092"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE scheduled_jobs j
        SET name = j.name || ' (' || d.name || ')'
        FROM schools s
        JOIN districts d ON d.id = s.district_id
        WHERE j.params->>'school_id' = s.id
          AND right(j.name, length(s.name) + 2) = ': ' || s.name
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE scheduled_jobs j
        SET name = left(j.name, length(j.name) - length(d.name) - 3)
        FROM schools s
        JOIN districts d ON d.id = s.district_id
        WHERE j.params->>'school_id' = s.id
          AND right(j.name, length(s.name) + length(d.name) + 5) = ': ' || s.name || ' (' || d.name || ')'
        """
    )
