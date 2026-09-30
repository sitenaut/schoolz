"""Machine translation of school-authored content (SchoolContentItem).

Same rule as extraction: translate once, share with everyone. The first
request in a language pays one Haiku call for whatever items are missing a
translation; the result is stored in `content_translations` and every later
visitor reads it. English never comes here.

Nothing in this module raises into a request. A missing API key, a model
error, a timeout, a malformed reply or an item the model skipped all mean
the same thing: that item is served in English, and the next request tries
again. The English text is always kept and returned alongside
(`title_original`), so a translated row can show what the school wrote.

Deterministic titles (the "Day 3" rotation markers) never reach the model -
services/i18n_strings.py handles them.
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from anthropic import AsyncAnthropic
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import observability
from models import ContentTranslation, School, SchoolContentItem
from services import i18n_strings

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
CHUNK_SIZE = 40
# One request never translates more than this many missing items (two
# concurrent chunks): a cold /calendar can hold hundreds, and a parent
# shouldn't wait on all of them. The rest are served in English and picked up
# by the next request - or by translate_school_content() in one go.
MAX_ITEMS_PER_REQUEST = 80
_TIMEOUT_S = 40.0
# After a failed call, stop calling for a while so an API outage doesn't add
# a doomed round trip to every page load.
_COOLDOWN_S = 60.0

LANGUAGE_NAMES = {
    "es": "US Spanish",
    "zh": "Simplified Chinese (as written in mainland China)",
    "ko": "Korean",
    "hi": "Hindi (Devanagari script)",
}

# The formal register in each language.
_REGISTER = {
    "es": 'Address families formally: "usted", never "tú" or "vosotros" (e.g. "Únase", not "Únete").',
    "zh": 'Address families respectfully with "您", never "你". Use Simplified characters and full-width Chinese punctuation.',
    "ko": 'Use the polite formal register of a school notice (합니다/하세요체, 존댓말), never 반말. Write grade numbers like "5th" as "5학년".',
    "hi": 'Address families respectfully with "आप", never "तुम" or "तू". Write in Devanagari; keep Western digits. Write grade numbers like "5th" as "5वीं कक्षा".',
}

_SYSTEM = """You translate short school-community notices from English into {language} for parents of school-age children.

Rules:
- Natural, warm, plain {language}, the way a school in the US would write to families. Same meaning and level of formality as the English. {register} Do not add, explain or omit anything.
- Do NOT translate proper nouns or names: people, schools, districts, programs, clubs, teams, businesses, product/app names, room names.
- Leave unchanged: room numbers, URLs, email addresses, phone numbers, dates and times (write "9:00 AM" as is), dollar amounts, grade numbers like "5th" (in Chinese write "5年级"), and codes such as "Day 3".
- Keep the line breaks, bullets and punctuation structure of the description.
- Translate every item you are given, keyed by its `n`. A description that is absent stays absent."""

_TOOL = {
    "name": "record_translations",
    "description": "Record the translation of each item.",
    "input_schema": {
        "type": "object",
        # `items` first: a long reply that hits max_tokens keeps every item
        # written so far (see CLAUDE.md, "items is declared FIRST").
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "description": "The item's number from the input."},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["n", "title"],
                },
            }
        },
        "required": ["items"],
    },
}


@dataclass(frozen=True)
class Localized:
    title: str
    description: str | None
    translated: bool  # machine-translated (False for English or a deterministic rendering)


_INFLIGHT: dict[tuple[str, str], "asyncio.Future[None]"] = {}
_cooldown_until = 0.0


def source_hash(title: str, description: str | None) -> str:
    return hashlib.sha256(f"{title}\n{description or ''}".encode()).hexdigest()


def _needs_model(item: SchoolContentItem, lang: str) -> bool:
    if i18n_strings.rotation_title(item.title, lang) is not None:
        return False
    return any(c.isalpha() for c in item.title)


async def _call_model(payload: list[dict], lang: str) -> dict[int, tuple[str, str | None]]:
    """One Haiku call. {n: (title, description)} for whatever came back."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    client = AsyncAnthropic(api_key=key, timeout=_TIMEOUT_S, max_retries=1)
    started = time.perf_counter()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=8192,
        temperature=0,
        system=_SYSTEM.format(language=LANGUAGE_NAMES[lang], register=_REGISTER[lang]),
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "record_translations"},
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    observability.record_llm_call("content_translation", MODEL, response, time.perf_counter() - started)
    if response.stop_reason == "max_tokens":
        logger.warning("content_translation_truncated", extra={"lang": lang, "items": len(payload)})
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    out: dict[int, tuple[str, str | None]] = {}
    for row in (tool_use.input.get("items") if tool_use else None) or []:
        if not isinstance(row, dict):
            continue
        n, title = row.get("n"), (row.get("title") or "").strip()
        if isinstance(n, int) and title:
            description = (row.get("description") or "").strip() or None
            out[n] = (title, description)
    return out


async def _translate_chunk(chunk: list[tuple[str, str, str | None]], lang: str) -> dict[str, tuple[str, str | None]]:
    """chunk: [(item_id, title, description)] -> {item_id: (title, description)}."""
    payload = []
    for n, (_, title, description) in enumerate(chunk):
        row: dict = {"n": n, "title": title}
        if description:
            row["description"] = description
        payload.append(row)
    got = await _call_model(payload, lang)
    out = {}
    for n, (item_id, _, description) in enumerate(chunk):
        if n not in got:
            continue
        title, translated_description = got[n]
        # An item with no English description never gains one.
        out[item_id] = (title, translated_description if description else None)
    return out


async def _stored(db: AsyncSession, ids: list[str], lang: str) -> dict[str, ContentTranslation]:
    if not ids:
        return {}
    rows = (await db.execute(select(ContentTranslation).where(ContentTranslation.lang == lang, ContentTranslation.item_id.in_(ids)).execution_options(populate_existing=True))).scalars().all()
    return {r.item_id: r for r in rows}


async def _save(db: AsyncSession, rows: list[dict]) -> None:
    stmt = pg_insert(ContentTranslation).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_content_translations_item_lang",
        set_={c: stmt.excluded[c] for c in ("title", "description", "source_hash", "model", "created_at")},
    )
    await db.execute(stmt)
    await db.commit()


async def translate_items(db: AsyncSession, items: list[SchoolContentItem], lang: str, limit: int | None = MAX_ITEMS_PER_REQUEST) -> int:
    """Makes sure every item that needs one has a fresh stored translation,
    calling the model for the missing/stale ones. Returns how many it newly
    stored. Never raises. `limit=None` translates everything (backfill)."""
    global _cooldown_until
    if lang not in LANGUAGE_NAMES:
        return 0
    try:
        wanted = [i for i in items if _needs_model(i, lang)]
        stored = await _stored(db, [i.id for i in wanted], lang)
        todo = [i for i in wanted if not (stored.get(i.id) and stored[i.id].source_hash == source_hash(i.title, i.description))]
        if not todo or time.monotonic() < _cooldown_until:
            return 0

        # Another request is already translating some of these: wait for it
        # rather than paying for the same call twice.
        mine = [i for i in todo if (i.id, lang) not in _INFLIGHT]
        theirs = [_INFLIGHT[(i.id, lang)] for i in todo if (i.id, lang) in _INFLIGHT]
        if limit is not None:
            mine = mine[:limit]
        loop = asyncio.get_running_loop()
        futures = {i.id: loop.create_future() for i in mine}
        for item_id, fut in futures.items():
            _INFLIGHT[(item_id, lang)] = fut

        saved = 0
        try:
            chunks = [[(i.id, i.title, i.description) for i in mine[k : k + CHUNK_SIZE]] for k in range(0, len(mine), CHUNK_SIZE)]
            hashes = {i.id: source_hash(i.title, i.description) for i in mine}
            results = await asyncio.gather(*[_translate_chunk(c, lang) for c in chunks], return_exceptions=True)
            rows = []
            for chunk, result in zip(chunks, results):
                if isinstance(result, BaseException):
                    _cooldown_until = time.monotonic() + _COOLDOWN_S
                    logger.warning("content_translation_failed", extra={"lang": lang, "items": len(chunk), "error": str(result)})
                    continue
                for item_id, (title, description) in result.items():
                    rows.append(
                        {
                            "item_id": item_id,
                            "lang": lang,
                            "title": title[:600],
                            "description": description,
                            "source_hash": hashes[item_id],
                            "model": MODEL,
                            "created_at": datetime.now(timezone.utc),
                        }
                    )
            if rows:
                await _save(db, rows)
                saved = len(rows)
        finally:
            for item_id, fut in futures.items():
                _INFLIGHT.pop((item_id, lang), None)
                if not fut.done():
                    fut.set_result(None)
        if theirs:
            await asyncio.wait(theirs, timeout=_TIMEOUT_S)
        return saved
    except Exception as exc:  # never into the request path
        logger.warning("content_translation_error", extra={"lang": lang, "error": str(exc)})
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


async def apply_translations(db: AsyncSession, items: list[SchoolContentItem], lang: str, translate_missing: bool = True) -> dict[str, Localized]:
    """{item_id: Localized} for every item, in `lang` where a fresh
    translation exists (translating what's missing first, unless
    `translate_missing` is False) and in the original English otherwise."""
    if lang not in LANGUAGE_NAMES:
        return {i.id: Localized(i.title, i.description, False) for i in items}
    if translate_missing:
        await translate_items(db, items, lang)
    try:
        stored = await _stored(db, [i.id for i in items if _needs_model(i, lang)], lang)
    except Exception as exc:
        logger.warning("content_translation_read_failed", extra={"lang": lang, "error": str(exc)})
        stored = {}
    out: dict[str, Localized] = {}
    for i in items:
        fixed = i18n_strings.rotation_title(i.title, lang)
        row = stored.get(i.id)
        if fixed is not None:
            out[i.id] = Localized(fixed, i.description, False)
        elif row and row.source_hash == source_hash(i.title, i.description):
            out[i.id] = Localized(row.title, row.description, True)
        else:
            out[i.id] = Localized(i.title, i.description, False)
    return out


def localize_out(out, item: SchoolContentItem, loc: Localized):
    """A SchoolContentItemOut in the item's translated text. The English is
    kept in title_original/description_original only when it was machine
    translated, so a caller can offer "show original"."""
    if not loc.translated and loc.title == item.title:
        return out
    update = {"title": loc.title, "description": loc.description}
    if loc.translated:
        update.update(translated=True, title_original=item.title, description_original=item.description)
    return out.model_copy(update=update)


async def localize_outs(db: AsyncSession, items: list[SchoolContentItem], outs: list, lang: str) -> list:
    """`outs[k]` is the SchoolContentItemOut of `items[k]`."""
    if lang not in LANGUAGE_NAMES or not items:
        return outs
    translations = await apply_translations(db, items, lang)
    return [localize_out(o, i, translations[i.id]) for i, o in zip(items, outs)]


async def translate_school_content(db: AsyncSession, school_id: str, lang: str) -> int:
    """Backfill: translate every current item a school's pages show (its own
    plus its district's), in as many calls as it takes. For a script or a
    one-off shell; returns how many translations were stored."""
    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return 0
    scope = SchoolContentItem.school_id == school_id
    if school.district_id:
        scope = or_(scope, SchoolContentItem.district_id == school.district_id)
    items = (await db.execute(select(SchoolContentItem).where(scope, SchoolContentItem.is_current.is_(True)).order_by(SchoolContentItem.start_date))).scalars().all()
    return await translate_items(db, list(items), lang, limit=None)
