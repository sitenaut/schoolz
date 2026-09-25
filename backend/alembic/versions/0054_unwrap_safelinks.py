"""unwrap Outlook Safe Links in stored link_url values

Data only. Newsletter blocks and the items extracted from them (and the HS
activities site's items) stored links exactly as published, including
Outlook `safelinks.protection.outlook.com/?url=...` wrappers carried over
from forwarded emails. New scans unwrap them (services/links.py); this
cleans what's already stored.

smore_blocks.content_hash is deliberately left alone: a link block's hash is
keyed on the URL as published, which is what the next scan hashes too.

The unwrap logic is copied here rather than imported so this migration keeps
meaning the same thing if services/links.py changes later.

Revision ID: 0054
Revises: 0053
Create Date: 2026-09-25 19:00:00

"""
import re
from typing import Sequence, Union
from urllib.parse import parse_qs, urlsplit

import sqlalchemy as sa
from alembic import op


revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HOST_RE = re.compile(r"(?:^|\.)safelinks\.protection\.outlook\.com$", re.I)


def _unwrap(url: str) -> str:
    for _ in range(3):
        parts = urlsplit(url.strip())
        if not _HOST_RE.search(parts.hostname or ""):
            return url
        target = (parse_qs(parts.query).get("url") or [""])[0].strip()
        if not target.lower().startswith(("http://", "https://")):
            return url
        url = target
    return url


def upgrade() -> None:
    conn = op.get_bind()
    for table in ("smore_blocks", "school_content_items"):
        rows = conn.execute(
            sa.text(f"SELECT id, link_url FROM {table} WHERE link_url ILIKE '%safelinks.protection.outlook.com%'")
        ).fetchall()
        for row_id, link in rows:
            unwrapped = _unwrap(link)
            if unwrapped != link:
                conn.execute(
                    sa.text(f"UPDATE {table} SET link_url = :link WHERE id = :id"),
                    {"link": unwrapped[:1000], "id": row_id},
                )


def downgrade() -> None:
    # The wrapped form carried nothing worth restoring.
    pass
