"""Scheduled job: backfill machine translations for every current
SchoolContentItem, so the first visitor to /es, /zh, /ko or /hi after a
district onboarding doesn't pay for the model call. Admin/run-now only (no
useful default cadence - new content is translated lazily on first view by
services/content_translation.apply_translations; this just pre-warms it in
bulk). Replaces running backend/scripts/backfill_translations.py by hand over
SSH on the scheduler machine - this runs the same calls through the normal
job pipeline instead."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School
from scheduler.registry import register_job
from services import content_translation
from services.content_translation import LANGUAGE_NAMES, translate_school_content

# A failed model call puts translate_items on a cooldown that silently skips
# every later school in the same pass; reset it before each call (same fix
# backend/scripts/backfill_translations.py uses) so one bad call doesn't
# starve the rest of the run. Sweep until a pass stores nothing new, since a
# chunk failure can leave some items for the next pass to pick up.
MAX_PASSES = 4

PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "langs": {
            "type": "array",
            "items": {"type": "string", "enum": list(LANGUAGE_NAMES)},
            "description": "Languages to backfill. Defaults to all supported languages.",
        }
    },
    "required": [],
}


@register_job(
    kind="translation_backfill.scan",
    default_name="Translation backfill",
    default_cron="0 7 * * 0",  # weekly Sunday 7am - mostly a run-now target
    default_params={"langs": list(LANGUAGE_NAMES)},
    description="Backfill machine translations for every current school content item in the given languages (default: all). Idempotent - only missing or stale translations are generated.",
    param_schema=PARAM_SCHEMA,
)
async def run(db: AsyncSession, params: dict) -> str | None:
    langs = [lang for lang in (params.get("langs") or list(LANGUAGE_NAMES)) if lang in LANGUAGE_NAMES]
    if not langs:
        return "WARNING[translation_backfill_no_langs]: no supported language in params.langs"

    school_ids = (await db.execute(select(School.id))).scalars().all()
    stored_by_lang: dict[str, int] = {}
    for lang in langs:
        total = 0
        for _ in range(MAX_PASSES):
            stored = 0
            for school_id in school_ids:
                content_translation._cooldown_until = 0.0
                stored += await translate_school_content(db, school_id, lang)
            total += stored
            if stored == 0:
                break
        stored_by_lang[lang] = total

    return f"stored translations: {stored_by_lang}"
