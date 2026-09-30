"""Translate every current school content item into the given languages, so
the first visitor to /es or /zh doesn't pay for the model call. Idempotent:
only missing or stale translations are generated.

Usage (from backend/): python scripts/backfill_translations.py es zh
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

import database
from models import School
from services import content_translation
from services.content_translation import LANGUAGE_NAMES, translate_school_content

MAX_PASSES = 4


async def main(langs: list[str]) -> None:
    bad = [lang for lang in langs if lang not in LANGUAGE_NAMES]
    if bad:
        sys.exit(f"unsupported language(s): {', '.join(bad)}")
    async with database.SessionLocal() as db:
        schools = (await db.execute(select(School.id, School.name).order_by(School.name))).all()
    for lang in langs:
        total = 0
        # A failed model call puts the whole process on a 60s cooldown that
        # silently skips every later school, so clear it before each call and
        # sweep again until a pass stores nothing new.
        for sweep in range(1, MAX_PASSES + 1):
            stored = 0
            for school_id, name in schools:
                content_translation._cooldown_until = 0.0
                async with database.SessionLocal() as db:
                    n = await translate_school_content(db, school_id, lang)
                stored += n
                if n:
                    print(f"[{lang}] pass {sweep} {name}: {n} translated", flush=True)
            total += stored
            print(f"[{lang}] pass {sweep}: {stored} stored", flush=True)
            if not stored:
                break
        print(f"[{lang}] done: {total} translations stored across {len(schools)} schools", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["es", "zh", "ko", "hi"]))
