"""localz: how Camden County families sign up for Toys for Tots in 2026

NJ 211's Camden County Toys for Tots listing still gives 2025's sign-up:
a registration day at the Elks Lodge on October 18, 2025, and an older
number for Clark Family Breast Cancer Services. The campaign's own page
(camden-nj.toysfortots.org, which refuses automated reads, so read by hand
in a browser on 2026-11-04) says who to call this year by where a family
lives, and that most of the county is already closed. Its document list
already matches NJ 211's "What to bring", so only "How to get help"
changes.

Two of the page's numbers are named volunteers' own, so the listing
points to the campaign's website for those instead: a listing's public
contact is a role, never a person (docs/LOCALZ_DESIGN.md). Clark Family
Breast Cancer Services' number is the organization's own published line.

NJ 211's detail refresh rewrites every field once a month, which would put
2025's text back before Christmas. So the field is marked as set by someone
other than the scraper (`provider_owned_fields`, as a reviewer's edit in
Admin does): a refresh then leaves it alone and turns NJ 211's differing
text into one source_conflict change request for a reviewer. The change is
logged in resource_change_log, so Admin can revert it like any other.

Only a listing that still carries NJ 211's 2025 text is changed.

Revision ID: 0146
Revises: 0145
Create Date: 2026-11-04 16:00:00
"""
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0146"
down_revision: str | None = "0145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NJ 211's id for "Holiday Toy Assistance - Camden County" (Toys for Tots).
_NJ211_ID = "6fed3531-282a-555d-9fe0-a4f92ef910c0"
FIELD = "application_process"
# In NJ 211's text while it still describes 2025's sign-up.
STALE_MARK = "October 18, 2025"

SIGN_UP = (
    "For 2026, families sign up by phone, and who to call depends on where you live. "
    "Cherry Hill and Pennsauken: Clark Family Breast Cancer Services, 856-317-1876. "
    "Fairview, Centerville, Downtown and North Camden in Camden City: call the number on the campaign's website. "
    "Closed for 2026: Whitman Park, Parkside, East Camden and Cramer Hill in Camden City (their sign-up day "
    "was October 17), and the rest of Camden County, including Blackwood, Clementon and Lindenwold."
)
NOTE = "Migration 0146: 2026 sign-up from the campaign's own page (camden-nj.toysfortots.org), read 2026-11-04"


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT id, application_process, provider_owned_fields FROM resource_services"
            " WHERE source = 'nj211' AND source_record_id = :rid"
        ),
        {"rid": _NJ211_ID},
    ).first()
    if row is None or FIELD in (row.provider_owned_fields or []) or STALE_MARK not in (row.application_process or ""):
        return
    conn.execute(
        sa.text(
            "UPDATE resource_services SET application_process = :text,"
            " provider_owned_fields = array_append(provider_owned_fields, :field), updated_at = now()"
            " WHERE id = :id"
        ),
        {"text": SIGN_UP, "field": FIELD, "id": row.id},
    )
    conn.execute(
        sa.text(
            "INSERT INTO resource_change_log (id, service_id, actor_kind, action, before, after, note, created_at)"
            " VALUES (:id, :service_id, 'system', 'reviewer.update', CAST(:before AS jsonb), CAST(:after AS jsonb),"
            " :note, now())"
        ),
        {
            "id": str(uuid.uuid4()),
            "service_id": row.id,
            "before": json.dumps({FIELD: row.application_process}),
            "after": json.dumps({FIELD: SIGN_UP}),
            "note": NOTE,
        },
    )


def downgrade() -> None:
    # The next NJ 211 detail refresh puts its own text back.
    op.get_bind().execute(
        sa.text(
            "UPDATE resource_services SET provider_owned_fields = array_remove(provider_owned_fields, :field),"
            " detail_fetched_at = NULL WHERE source = 'nj211' AND source_record_id = :rid AND application_process = :text"
        ),
        {"field": FIELD, "rid": _NJ211_ID, "text": SIGN_UP},
    )
    op.get_bind().execute(sa.text("DELETE FROM resource_change_log WHERE note = :note"), {"note": NOTE})
