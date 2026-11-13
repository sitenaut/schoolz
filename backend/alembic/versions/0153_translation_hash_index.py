"""content_translations: index (lang, source_hash)

services/content_translation._reuse_by_hash copies an existing translation of
identical English text by looking it up by `lang` and `source_hash`. Only
(item_id, lang) was indexed, so every lookup read the whole table, the
database's largest (~76 MB of rows on a database whose cache can't hold it,
so a read from disk each time). It runs whenever a page in another language
has an item still untranslated: the nightly prerender of every school page
in four languages, the weekly backfill (every school, four languages, up to
four passes), and crawler visits. That drained Supabase's Disk IO budget.

A plain CREATE INDEX, not CONCURRENTLY: only the translation worker writes
to this table, and a build of this size takes seconds. If it can't get its
lock within the migration's lock_timeout it rolls back cleanly and the
deploy stops on the old version, rather than leaving an invalid index that
`IF NOT EXISTS` would then keep.

Revision ID: 0153
Revises: 0152
Create Date: 2026-11-12 00:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0153"
down_revision: str | None = "0152"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_content_translations_lang_source_hash", "content_translations", ["lang", "source_hash"])


def downgrade() -> None:
    op.drop_index("ix_content_translations_lang_source_hash", table_name="content_translations")
