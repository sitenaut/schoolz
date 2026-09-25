"""Turns newly-scanned SmoreBlock rows into structured SchoolContentItem
rows: a topical summary, calendar-able events/deadlines/initiatives,
reminders, program/busing/funding/volunteer/org/merch info, a PTA section,
staff people, and (only when the source text itself says something is new
or changed) policy/procedure updates.

Two Claude calls: a vision pass over any new image blocks (flyers carry no
text otherwise - confirmed on real newsletters), then one structured
text-extraction call over everything (block text + vision-extracted image
text), with the school's current items given as context so a corrected
date/typo can supersede the old item instead of creating a confusing
duplicate calendar entry.
"""

import base64
import io
import logging
import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from anthropic import AsyncAnthropic
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import observability
from models import LunchMenu, LunchMenuItem, School, SchoolContentItem, SmoreBlock, SmoreNewsletter, StaffMember, normalize_name
from services.links import unwrap_redirect
from services.school_status import is_status_title, same_status_fact
from services.tool_output import object_list, recover_spilled_input
from scheduler.errors import record_parse_issue

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-haiku-4-5-20251001"

# Known parent/student information system login URLs, keyed by lowercased
# name - resolved deterministically rather than trusting the model to
# invent or copy a URL, since a newsletter naming "Genesis" rarely also
# includes the actual login link. Confirmed real: Cherry Hill Public
# Schools' Genesis Parent Access portal is a single district-wide URL (a
# global nav link on every school's own site, not something per-school).
_KNOWN_PORTAL_URLS = {
    "genesis": "https://parents.chclc.org/genesis/parents?gohome=true",
}

_CATEGORIES = [
    "event", "deadline", "initiative", "reminder", "policy_change", "procedure",
    "program", "busing", "funding", "volunteer", "org_club", "merch_ad", "pta", "person", "lunch_menu",
]

_EXTRACTION_TOOL = {
    "name": "record_extraction",
    "description": "Records structured items extracted from a school newsletter.",
    "input_schema": {
        "type": "object",
        "properties": {
            # "items" is declared FIRST deliberately: Claude generates
            # tool-use JSON fields in schema property order, and a long
            # newsletter can exceed max_tokens mid-response - if that
            # happens, we want the items truncated, not dropped entirely
            # (confirmed in testing: with "items" last, a real 37-block
            # newsletter hit max_tokens after the summary/school fields and
            # produced zero items even though input tokens were fine).
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": _CATEGORIES,
                            "description": "'lunch_menu' for a day-by-day meal calendar flyer (e.g. a monthly lunch/breakfast menu image) - "
                            "put the full day-by-day breakdown in description, one item per menu period (e.g. one per month) "
                            "rather than one item per day.",
                        },
                        "scope": {
                            "type": "string",
                            "enum": ["school", "district"],
                            "description": "'district' if this applies to the WHOLE district, not just this school - district-wide holidays/closures (Labor Day, Yom Kippur, etc), district-wide policy changes, district-wide deadlines. 'school' (default) for anything specific to this one school (its own PTA, its own procedures, its own programs). When unsure, use 'school'.",
                        },
                        "title": {
                            "type": "string",
                            "description": "For category='person', this MUST be the person's actual name (e.g. 'Sara Egan'), with their role in person_title (e.g. 'School Counselor') - never put a role/title here instead of a name.",
                        },
                        "description": {"type": "string"},
                        "start_date": {"type": "string", "description": "Date/time in the school's own local time, as 'YYYY-MM-DD' (all-day) or 'YYYY-MM-DDTHH:MM:SS' (timed) - no 'Z' or UTC offset, this is local wall-clock time, not UTC. REQUIRED for category='lunch_menu' even though the item covers a whole month - use the first of that month (e.g. '2026-09-01'), since this is what tells us which year/month the day-by-day breakdown in description applies to."},
                        "end_date": {"type": "string", "description": "Same local-time format as start_date, for date ranges."},
                        "link_url": {
                            "type": "string",
                            "description": "The URL from the source block's '(link: ...)' annotation, if that block has one - ALWAYS include it here when present, even if the item also has other fields. Never drop a link.",
                        },
                        "person_name": {"type": "string"},
                        "person_title": {"type": "string"},
                        "source_block_position": {"type": "integer"},
                        "source_excerpt": {"type": "string"},
                        "supersedes_item_id": {
                            "type": "string",
                            "description": "Set ONLY if this item corrects/updates one of the CURRENT ITEMS given in context (same event, corrected date, typo fix, etc) - the id of that existing item.",
                        },
                    },
                    "required": ["category", "title"],
                },
            },
            "summary": {"type": "string", "description": "2-4 sentence topical summary of what's new/notable in this newsletter, for display at the top of the school page."},
            "school_name": {"type": "string"},
            "school_address": {"type": "string"},
            "school_main_phone": {"type": "string"},
            "absence_method": {"type": "string", "enum": ["email", "phone", "portal", "other"]},
            "absence_emails": {"type": "array", "items": {"type": "string"}},
            "absence_phone": {"type": "string"},
            "absence_portal_name": {
                "type": "string",
                "description": "Set ONLY when absence_method is 'portal' - the name of the parent/student information "
                "system the text directs parents to use (e.g. 'Genesis', 'ParentVUE', 'Skyward'). Do NOT set "
                "absence_instructions when using 'portal' - the portal name/link is enough, no need to also copy the "
                "full click-by-click steps.",
            },
            "absence_instructions": {
                "type": "string",
                "description": "Raw instructions for reporting an absence, verbatim-ish. Only for methods OTHER than "
                "'portal' - a portal login flow's full step-by-step text is not worth surfacing to a parent, the portal "
                "link itself is.",
            },
        },
        "required": ["summary", "items"],
    },
}

_SYSTEM_PROMPT = """You extract structured information from a school newsletter for parents. \
Only extract policy_change or procedure items when the text EXPLICITLY says something is new, \
changed, or updated - never extract routine/unchanging policy text under those two categories. \
Dates should be resolved to actual ISO 8601 dates when the text gives enough context (e.g. a \
year from the newsletter's own dateline); omit start_date/end_date if you can't determine an \
actual date. If an item clearly corrects or updates one of the CURRENT ITEMS given to you \
(same event/deadline, different date, typo fix), set supersedes_item_id to that item's id \
instead of creating a duplicate. Every link mentioned in the source (marked "(link: ...)") must \
be preserved - if an item is based on a block with a link annotation, copy that URL into the \
item's link_url field. Never omit a link that's present in the source. Set scope='district' for \
anything that applies district-wide (school closures/holidays, district-wide policy or deadlines) \
rather than being specific to this one school - this school's newsletter reports district holidays \
too, but every other school in the district reports the exact same ones, so marking them 'district' \
lets them be shown once instead of once per school. \
Extract EVERY distinct dated item you find, including EVERY separate bullet/line inside a "Mark Your \
Calendar", "Upcoming Events", or similar list block - each one (each closure, each early dismissal, \
each first-day-of-school date, etc) is its own item, never summarized into one combined item or \
skipped. Every flyer/image block's content must be represented by at least one item - do not silently \
omit an entire flyer (e.g. a "Back to School Night" flyer, a lunch menu) just because other blocks in \
the same newsletter already produced items. Completeness matters more than brevity here."""


_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
_MAX_IMAGE_BYTES = 4_500_000  # the API rejects images over 5MB
_MAX_IMAGE_EDGE = 1568  # what the API downsamples to anyway; re-encoding to it keeps flyers under the byte cap


def _sniff_media_type(data: bytes) -> str | None:
    for magic, media_type in _MAGIC:
        if data.startswith(magic):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _prepare_image(data: bytes) -> tuple[bytes, str] | None:
    """Returns (bytes, media_type) the vision API will accept, or None.

    Never trusts the CDN's Content-Type: Smore serves PNGs labelled
    image/jpeg and the odd "image/jpg"/octet-stream, each of which the
    API rejects outright (confirmed on real newsletters). Sniffs the
    bytes instead, and re-encodes anything oversized or in a format the
    API doesn't take (AVIF, BMP, ...) via Pillow.
    """
    media_type = _sniff_media_type(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            if media_type and len(data) <= _MAX_IMAGE_BYTES and max(img.size) <= _MAX_IMAGE_EDGE * 2:
                return data, media_type
            rgb = img.convert("RGB")
            rgb.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE))
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=85, optimize=True)
    except (UnidentifiedImageError, OSError):
        return None
    return out.getvalue(), "image/jpeg"


# TODO(image-fetch-forbidden, confirmed 2026-09-13 on Beck's newsletter):
# every failure in _vision_extract - an image Pillow can't parse, a
# network timeout, or the source actively blocking the request - collapses
# to the same "image_unsupported" warning/parse-issue code below. A real
# case: a Google Sites embed's preview image at lh3.googleusercontent.com
# returns 403 Forbidden to a plain server-side fetch (confirmed by
# fetching it directly - Google's CDN is blocking the request itself, not
# serving a corrupted/unsupported image). Two improvements, low priority
# since the block's own text_content already carried the real content in
# this case: (1) a distinct error code (e.g. image_fetch_forbidden) so this
# doesn't read as a format problem; (2) route the fetch through the
# scraper's fetch_raw (real browser fingerprint) the way other
# bot-blocked downloads already do, rather than a bare httpx.get() here.
async def _vision_extract(client: AsyncAnthropic, image_url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http_client:
            resp = await http_client.get(image_url)
            resp.raise_for_status()
        prepared = _prepare_image(resp.content)
        if prepared is None:
            logger.warning("vision_extraction_unsupported_image", extra={"image_url": image_url})
            record_parse_issue("smore.scan", "image_unsupported", url=image_url)
            return None
        image_bytes, media_type = prepared
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        _llm_started = time.perf_counter()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                        {
                            "type": "text",
                            "text": "Transcribe all text in this image verbatim, and describe any dates, "
                            "events, deadlines, names, or contact info shown. This is a flyer from a "
                            "school newsletter for parents.",
                        },
                    ],
                }
            ],
        )
        observability.record_llm_call("vision_extract", MODEL, response, time.perf_counter() - _llm_started)
        return "".join(block.text for block in response.content if block.type == "text")
    except Exception:
        logger.exception("vision_extraction_failed", extra={"image_url": image_url})
        return None


_DEFAULT_TZ = ZoneInfo("America/New_York")

# Matches the model's own "[Weekday] [M/]DD: description." shape for a
# lunch_menu item's description (confirmed real on Chesterbrook Academy
# flyers) - split deterministically rather than a second LLM round-trip,
# since the format the model already produces is regular enough to parse
# with a regex. The weekday name and month prefix are both optional per
# match: a real Chesterbrook menu grouped entries by day-of-week and only
# repeated the weekday label on the first entry of each group ("Monday
# 9/1: ... ; 9/8: ... ; 9/15: ..."), and redundantly included the month
# alongside the day (matching this item's own year/month, already known
# from item_start_date - the month digit is discarded, only the day is
# captured). Anything before the first match (a title line) and after the
# last (a trailing "Available daily: ..." note) is simply not a day entry
# and is dropped here, not lost - the raw description stays on the
# SchoolContentItem row this was parsed from.
_MENU_DAY_RE = re.compile(
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+)?(?:\d{1,2}/)?(\d{1,2}):\s*"
)


_MENU_TRAILING_NOTE_RE = re.compile(r"\.?\s*Available daily:.*$", re.IGNORECASE)


def _parse_lunch_menu_days(description: str, year: int, month: int) -> list[dict]:
    description = _MENU_TRAILING_NOTE_RE.sub("", description)
    matches = list(_MENU_DAY_RE.finditer(description))
    days = []
    for i, m in enumerate(matches):
        day = int(m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(description)
        # ". " and "; " both seen as the model's chosen entry separator
        # across real newsletters - strip whichever trails this entry.
        text = description[m.end() : end].strip().rstrip(".;").strip()
        if not text:
            continue
        try:
            date = datetime(year, month, day, tzinfo=_DEFAULT_TZ)
        except ValueError:
            continue
        days.append({"date": date, "description": text})
    return days


_MONTH_YEAR_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s*,?\s*(\d{4})?",
    re.IGNORECASE,
)
_MONTH_NUM = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], start=1
)}


def _infer_lunch_menu_start_date(item: dict, extracted_at: datetime) -> datetime | None:
    """The model is asked to always set start_date to the first of the
    applicable month for a lunch_menu item, but omits it often enough
    (confirmed real: a Chesterbrook Academy menu with no start_date at all,
    which silently skipped the whole day-by-day parse below - the item sat
    inert in school_content_items with no UI surface, since the frontend
    only ever reads the structured LunchMenu/LunchMenuItem tables, never
    this category directly) that a fallback is worth having. Tries a
    "Month[, YYYY]" mention in the item's own title/description first (a
    menu almost always names its own month), then falls back to the
    extraction run's own date - a lunch menu newsletter is close to always
    about the current or very-near-future month."""
    text = f"{item.get('title') or ''} {item.get('description') or ''}"
    m = _MONTH_YEAR_RE.search(text)
    if m:
        month = _MONTH_NUM[m.group(1).lower()]
        year = int(m.group(2)) if m.group(2) else extracted_at.year
        try:
            return datetime(year, month, 1, tzinfo=_DEFAULT_TZ)
        except ValueError:
            pass
    return datetime(extracted_at.year, extracted_at.month, 1, tzinfo=_DEFAULT_TZ)


def _parse_date(value: str | None) -> datetime | None:
    """Claude is asked for ISO dates but has no real notion of timezone -
    it reasons in the school's own local time. A bare date/time with no
    offset is therefore local (America/New_York), not UTC; treating it as
    UTC silently shifted every all-day date back a day and every timed
    event by 4-5 hours in testing (Labor Day showing as Sept 6 instead of
    Sept 7, a 6pm PTA meeting showing as 2pm)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        record_parse_issue("smore.scan", "unexpected_format", sample=value[:200])
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_DEFAULT_TZ)
    return parsed


# A newsletter scanned today essentially never advertises an event that
# already happened a year ago - but a flyer can still *say* it does.
# Confirmed real (Chesterbrook Academy, Sept 2026): the preschool PTA
# reused last year's Ice Cream Social artwork, which prints "SEPTEMBER 24,
# 2025" in 40pt type. The vision pass transcribed that faithfully and the
# extraction trusted an explicit year over a sibling block's bare "9/24",
# so the event landed twelve months in the past - dropping out of every
# forward-looking surface (Coming up, Today, the September calendar)
# rather than merely showing a wrong date. Rolling the year forward to the
# next plausible occurrence beats storing a date we already know is stale;
# the grace window keeps a genuinely just-passed event (still being
# reported a week or two after the fact) from being shoved a year ahead.
_STALE_DATE_GRACE = timedelta(days=30)
_MAX_YEAR_ROLL = 5


def _add_years(value: datetime, years: int) -> datetime:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)  # Feb 29 in a non-leap year


def _correct_stale_year(parsed: datetime | None, reference: datetime | None = None, **context) -> datetime | None:
    """Rolls a stale-looking date forward to its next plausible occurrence."""
    if parsed is None:
        return None
    reference = reference or datetime.now(_DEFAULT_TZ)
    cutoff = reference - _STALE_DATE_GRACE
    if parsed >= cutoff:
        return parsed
    for years in range(1, _MAX_YEAR_ROLL + 1):
        candidate = _add_years(parsed, years)
        if candidate >= cutoff:
            record_parse_issue(
                "smore.scan", "stale_year", sample=f"{parsed.date()} -> {candidate.date()}", **context
            )
            return candidate
    # Older than _MAX_YEAR_ROLL and so not a plausibly mis-yeared current
    # event - more likely a genuine historical reference. Leave it alone.
    return parsed


# Single-digit-ordinal only - the realistic range for a "Nth day of X"
# school title ("First/1st Day of School", "First/1st Day of Autumn"), not
# a general-purpose ordinal normalizer.
_ORDINAL_WORD_TO_NUM = {
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
}
_ORDINAL_SUFFIX = {"1": "st", "2": "nd", "3": "rd"}


def _fold_ordinal_word(word: str) -> str:
    num = _ORDINAL_WORD_TO_NUM.get(word)
    return num + _ORDINAL_SUFFIX.get(num, "th") if num else word


def _title_dedup_key(title: str) -> str:
    """normalize_name plus ordinal word/numeral folding, so two newsletters
    phrasing the same day marker differently are recognised as the same
    fact rather than two events. Confirmed real: the same Chesterbrook date
    produced both "First Day of Autumn" and "1st Day of Autumn" from two
    separate newsletter extractions - an exact-title dedup check doesn't
    catch it, and there's no closure/status wording here for
    same_status_fact to match on either. This is the general case that
    exists for, one step narrower than a full fuzzy-title dedup."""
    return " ".join(_fold_ordinal_word(w) for w in normalize_name(title).split(" "))


def _may_supersede(old: SchoolContentItem, new: SchoolContentItem, reference: datetime | None = None) -> bool:
    """Guards the model's own supersedes_item_id against retiring a live
    item in favour of one that has already happened.

    The stale-year correction above handles the dates we can recognise as
    wrong; this is the second line of defence for the ones we can't. A
    newer extraction is normally the better one (a corrected date, a typo
    fix, a fuller description), which is why supersede exists at all - but
    "newer" stops meaning "better" the moment the replacement is dated in
    the past and the item it would retire is still upcoming. That exact
    swap is what hid Chesterbrook's Ice Cream Social: a richer flyer block
    (time, location, ticket price) carrying last year's date superseded the
    correctly-dated row extracted from the plain "Upcoming Events" list.
    """
    if old.start_date is None or new.start_date is None:
        return True
    reference = reference or datetime.now(_DEFAULT_TZ)
    if new.start_date < reference <= old.start_date:
        record_parse_issue(
            "smore.scan",
            "stale_supersede",
            sample=f"{new.title[:60]}: {new.start_date.date()} would retire {old.start_date.date()}",
        )
        return False
    return True


def _backfill_from_duplicate(existing: SchoolContentItem, item: dict, link_url: str | None) -> bool:
    """Fills gaps on the row we're keeping from the duplicate we're dropping.

    The dedup below is first-wins, which is arbitrary with respect to
    quality: a newsletter announces the same event in several blocks, and
    the terse one can easily be extracted first. Confirmed real - East's
    "Back to School Night" appeared in four per-cohort "important dates"
    lists with **no description at all**, plus a dedicated flyer block
    carrying the full paragraph (7:00 PM, parking, Block A, Parent Portal).
    The flyer was extracted in a later run, so a bare skip would have
    discarded the only useful copy and kept an empty row permanently.

    Only ever fills a field that is currently empty - never overwrites text
    already on the row, since "longer" is not reliably "better".
    """
    changed = False
    description = (item.get("description") or "").strip()
    if description and not (existing.description or "").strip():
        existing.description = description
        changed = True
    if link_url and not existing.link_url:
        existing.link_url = link_url
        changed = True
    return changed


async def extract_from_newsletter(db: AsyncSession, newsletter: SmoreNewsletter, new_blocks: list[SmoreBlock]) -> str:
    if not ANTHROPIC_API_KEY:
        return "skipped - ANTHROPIC_API_KEY not configured"
    if not new_blocks:
        return "no new blocks to extract from"

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    vision_failures = 0
    for block in new_blocks:
        if block.block_type == "image" and block.pending_vision_extraction:
            text = await _vision_extract(client, block.image_url)
            if text is None:
                # Leave it pending: flipping the flag on failure used to mark
                # the flyer as done with no text - permanently, since only
                # never-seen blocks get another look - so a transient API
                # error silently dropped whole flyers with a "success" run.
                vision_failures += 1
                continue
            block.vision_extracted_text = text
            block.pending_vision_extraction = False
    await db.flush()

    def _corpus_line(block: SmoreBlock) -> str | None:
        text = block.text_content or block.vision_extracted_text
        # Always surface the block's link explicitly, even when it also has
        # text - the visible text (e.g. "Click here") often doesn't mention
        # the URL itself, so the model would otherwise never see it.
        link_suffix = f" (link: {block.link_url})" if block.link_url else ""
        if text:
            return f"[block {block.position}, {block.block_type}] {text}{link_suffix}"
        if block.link_url:
            return f"[block {block.position}, link] {block.link_url}"
        return None

    vision_note = (
        f"WARNING[image_unsupported]: {vision_failures} image block(s) failed vision extraction (left pending) · "
        if vision_failures
        else ""
    )
    extractable_blocks = [b for b in new_blocks if _corpus_line(b) is not None]
    if not extractable_blocks:
        return f"{vision_note}no extractable text in new blocks"

    school_id = newsletter.school_id
    school = None
    if school_id:
        school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()

    # Preload the school's staff roster once, keyed by normalized name, so
    # every "person" mention (and any other item that happens to name
    # someone) can resolve back to a real StaffMember instead of floating
    # free text - the whole point of scanning rosters in the first place.
    staff_by_name: dict[str, str] = {}
    if school_id:
        staff_result = await db.execute(select(StaffMember).where(StaffMember.school_id == school_id))
        staff_by_name = {normalize_name(s.full_name): s.id for s in staff_result.scalars().all()}

    district_id = newsletter.district_id or (school.district_id if school else None)

    created = 0
    skipped_dupes = 0
    truncated_chunks = 0
    latest_summary = None

    # One Claude call per newsletter used to mean one big-enough newsletter
    # could blow the whole extraction: a real 37-block Bret Harte issue
    # (heavy on verbose vision transcriptions) hit max_tokens=8192 and came
    # back with *zero* items despite "items" being schema-ordered first -
    # the model hadn't finished writing even the first item before the
    # cutoff. Chunking keeps each call's output comfortably under the
    # ceiling, so a big newsletter degrades to "one busy flyer's worth of
    # items lands in the next chunk" instead of "the whole issue vanishes".
    _CHUNK_SIZE = 12
    for chunk_start in range(0, len(extractable_blocks), _CHUNK_SIZE):
        chunk = extractable_blocks[chunk_start : chunk_start + _CHUNK_SIZE]
        corpus_lines = [line for b in chunk if (line := _corpus_line(b)) is not None]

        current_items_context = ""
        if school_id:
            result = await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.school_id == school_id, SchoolContentItem.is_current.is_(True)
                )
            )
            current = result.scalars().all()
            if current:
                lines = [f"- id={i.id} [{i.category}] {i.title} (start_date={i.start_date})" for i in current]
                current_items_context = "\n\nCURRENT ITEMS for this school (reference by id in supersedes_item_id if one of these is being corrected/updated):\n" + "\n".join(lines)

        _llm_started = time.perf_counter()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=8192,
            temperature=0,
            system=_SYSTEM_PROMPT,
            tools=[_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "record_extraction"},
            messages=[{"role": "user", "content": "\n".join(corpus_lines) + current_items_context}],
        )
        observability.record_llm_call("content_extract", MODEL, response, time.perf_counter() - _llm_started)
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if not tool_use:
            continue
        data = recover_spilled_input(tool_use.input)
        if response.stop_reason == "max_tokens":
            truncated_chunks += 1
            logger.warning("extraction_chunk_truncated", extra={"newsletter_id": newsletter.id, "usage": str(response.usage)})
            record_parse_issue("smore.scan", "llm_max_tokens", newsletter_id=newsletter.id)

        if school:
            if not school.address and data.get("school_address"):
                school.address = data["school_address"]
            if not school.main_phone and data.get("school_main_phone"):
                school.main_phone = data["school_main_phone"]
            if not school.absence_method and data.get("absence_method"):
                school.absence_method = data["absence_method"]
                school.absence_emails = data.get("absence_emails", [])
                school.absence_phone = data.get("absence_phone")
                if data["absence_method"] == "portal":
                    portal_name = (data.get("absence_portal_name") or "").strip()
                    school.absence_portal_name = portal_name or None
                    school.absence_portal_url = _KNOWN_PORTAL_URLS.get(portal_name.lower())
                    # The click-by-click login flow isn't worth surfacing
                    # once we have a direct portal link - the button should
                    # link out, not reprint a paragraph of steps.
                    school.absence_instructions = None
                else:
                    school.absence_instructions = data.get("absence_instructions")
        if data.get("summary"):
            latest_summary = data["summary"]

        block_by_position = {b.position: b for b in chunk}
        items, dropped = object_list(data.get("items"))
        if dropped:
            record_parse_issue("smore.scan", "unexpected_format", newsletter_id=newsletter.id, sample=str(dropped)[:200])
        for item in items:
            source_block = block_by_position.get(item.get("source_block_position"))
            source_block_id = source_block.id if source_block else None
            # Infer from the date string itself ('T' means a time was given)
            # rather than trusting a separate is_all_day flag - the model
            # reliably omits that flag, and item.get(..., True) silently
            # defaulted every timed event to "all day" in testing.
            is_all_day = "T" not in (item.get("start_date") or "")
            # Backfill from the source block if the model dropped the link -
            # the prompt asks it to always copy it over, but don't rely on
            # that alone; the block's own link_url is ground truth we
            # already have.
            link_url = unwrap_redirect(item.get("link_url") or (source_block.link_url if source_block else None))
            person_name = item.get("person_name")
            # Confirmed real case: despite the schema wording, the model
            # sometimes puts the person's name in `title` instead of
            # `person_name` for category="person" items. Try both rather
            # than relying on the model to always follow the field split.
            name_candidates = [n for n in (person_name, item.get("title") if item["category"] == "person" else None) if n]
            staff_member_id = next(
                (staff_by_name[normalize_name(n)] for n in name_candidates if normalize_name(n) in staff_by_name), None
            )

            raw_start_date = _parse_date(item.get("start_date"))
            item_start_date = _correct_stale_year(raw_start_date, newsletter_id=newsletter.id)
            # Keep a date range intact: if the start rolled forward a year,
            # the end moves with it rather than being corrected on its own
            # (an end date judged against the same cutoff could otherwise
            # land a different number of years away from its own start).
            year_shift = (item_start_date.year - raw_start_date.year) if (raw_start_date and item_start_date) else 0
            item_end_date = _parse_date(item.get("end_date"))
            if item_end_date is not None:
                item_end_date = (
                    _add_years(item_end_date, year_shift)
                    if year_shift
                    else _correct_stale_year(item_end_date, newsletter_id=newsletter.id)
                )
            if item_start_date is None and item["category"] == "lunch_menu":
                item_start_date = _infer_lunch_menu_start_date(item, datetime.now(_DEFAULT_TZ))
                record_parse_issue("smore.scan", "unexpected_format", newsletter_id=newsletter.id, sample="lunch_menu item missing start_date")

            if item["category"] == "lunch_menu" and school_id and item_start_date and item.get("description"):
                days = _parse_lunch_menu_days(item["description"], item_start_date.year, item_start_date.month)
                if not days:
                    record_parse_issue(
                        "smore.scan", "unexpected_format", newsletter_id=newsletter.id,
                        sample=item["description"][:200],
                    )
                if days:
                    meal_type = "breakfast" if "breakfast" in item["title"].lower() else "lunch"
                    source_url = link_url or (source_block.image_url if source_block else None) or f"newsletter:{newsletter.id}:block:{item.get('source_block_position')}"
                    menu = (
                        await db.execute(
                            select(LunchMenu).where(LunchMenu.school_id == school_id, LunchMenu.meal_type == meal_type, LunchMenu.source_pdf_url == source_url)
                        )
                    ).scalar_one_or_none()
                    if not menu:
                        menu = LunchMenu(
                            school_id=school_id,
                            school_type=school.school_type if school else None,
                            meal_type=meal_type,
                            period_label=item_start_date.strftime("%B %Y"),
                            source_pdf_url=source_url,
                        )
                        db.add(menu)
                        await db.flush()
                    existing_days = (
                        await db.execute(select(LunchMenuItem.menu_date).where(LunchMenuItem.lunch_menu_id == menu.id))
                    ).scalars().all()
                    existing_dates = {d.date() for d in existing_days}
                    for day in days:
                        if day["date"].date() in existing_dates:
                            continue
                        db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=day["date"], description=day["description"]))
                    created += 1
                    continue
                # Parsing produced nothing usable (format didn't match) -
                # fall through and keep the raw description as a plain item
                # instead of silently losing the flyer's content.

            scope = item.get("scope") if item.get("scope") in ("school", "district") else "school"
            if not school_id and district_id:
                # A district-wide newsletter (no dedicated school - e.g.
                # "CHPS Weekly") has nowhere to attach a scope="school" item
                # at all, so every item here is district-scoped regardless
                # of what the model guessed.
                scope = "district"
            elif district_id and is_status_title(item["title"]):
                # "No school today"/"early dismissal"/"delayed opening" is
                # never really one school's own news - every school in the
                # district shares the same closed/half-day/delayed calendar
                # - but the model doesn't reliably mark these scope='district'
                # even though its own prompt says to (confirmed real: Kilmer's
                # newsletter reported "First Day of School (early dismissal)"
                # as scope='school', while other schools' newsletters
                # independently reported the same district-wide fact too,
                # producing a pile of near-duplicate "First Day of School"
                # items - one per school - instead of one shared row).
                # Forcing it here, rather than trusting the prompt alone,
                # means the dedup check just below always gets a chance to
                # collapse it into the one existing district row.
                scope = "district"
            item_school_id = school_id
            item_district_id = None
            if scope == "district" and district_id:
                # Dedup: every school in the district reports the same
                # holiday independently in its own newsletter - one row per
                # (district, category, date), not one per school's
                # re-telling of it. The rotation feeds put a
                # category="event" "Day N" marker on nearly every school day
                # (elementary via ICS, high school via the rotation PDF -
                # often both on one date). Those aren't "the same item" as a
                # newsletter's district-wide event that day, so they're
                # excluded here: matching them either crashed this lookup
                # (two rotation rows -> MultipleResultsFound, seen in prod)
                # or, worse, silently skipped the newsletter's event as a
                # duplicate of "Day 3". Same ^Day \d$ convention
                # school_today.py uses to recognise rotation markers.
                district_candidates = (
                    await db.execute(
                        select(SchoolContentItem).where(
                            SchoolContentItem.scope == "district",
                            SchoolContentItem.district_id == district_id,
                            SchoolContentItem.start_date == item_start_date,
                            ~SchoolContentItem.title.regexp_match(r"^Day \d$"),
                        )
                    )
                ).scalars().all()
                # Matching on category alone missed a real duplicate: "Board
                # of Education Election Day" was extracted twice for the same
                # date, once as category="reminder" and once as "event", so
                # the categories never lined up. The title and status checks
                # are purely additive - category matching still carries the
                # original case this dedup exists for, where one school's
                # newsletter says plain "Labor Day" and another's says
                # something else entirely on the same district-wide date.
                new_title = item["title"][:300]
                if any(
                    c.category == item["category"]
                    or _title_dedup_key(c.title) == _title_dedup_key(new_title)
                    or same_status_fact(c.title, new_title)
                    for c in district_candidates
                ):
                    skipped_dupes += 1
                    continue
                item_school_id = None
                item_district_id = district_id
            else:
                scope = "school"
                # Dedup: the same event can be mentioned in more than one
                # block of the same newsletter (a prose "coming up"
                # paragraph and a separate "Mark your calendar" list are
                # both real, confirmed cases) - block-level dedup is
                # exact-content-hash, so two different blocks describing
                # the same event never collide there. Since block-hash
                # dedup can't catch this, catch it here instead: an
                # unchanged (school, category, title, date) already on
                # file is the same fact restated, not a second occurrence
                # of it. Keyed with title (unlike the district dedup
                # above) since a school's own day can legitimately have
                # two different events of the same category.
                #
                # Matched via _title_dedup_key, not an exact string - two
                # separate extraction runs produced "First Day of Autumn"
                # and "1st Day of Autumn" for the same Chesterbrook date,
                # and an exact match let the second one straight through.
                new_title = item["title"][:300]
                school_candidates = (
                    await db.execute(
                        select(SchoolContentItem).where(
                            SchoolContentItem.scope == "school",
                            SchoolContentItem.school_id == school_id,
                            SchoolContentItem.category == item["category"],
                            SchoolContentItem.start_date == item_start_date,
                            SchoolContentItem.is_current.is_(True),
                        )
                    )
                ).scalars().all()
                existing_row = next(
                    (c for c in school_candidates if _title_dedup_key(c.title) == _title_dedup_key(new_title)), None
                )
                if existing_row is not None:
                    # Keep the row already on file, but take anything it's
                    # missing from this restatement first - see
                    # _backfill_from_duplicate for why a bare skip lost data.
                    _backfill_from_duplicate(existing_row, item, link_url)
                    skipped_dupes += 1
                    continue

            new_item = SchoolContentItem(
                scope=scope,
                school_id=item_school_id,
                district_id=item_district_id,
                newsletter_id=newsletter.id,
                source_block_id=source_block_id,
                category=item["category"],
                title=item["title"][:300],
                description=item.get("description"),
                start_date=item_start_date,
                end_date=item_end_date,
                is_all_day=is_all_day,
                link_url=link_url,
                person_name=person_name,
                person_title=item.get("person_title"),
                staff_member_id=staff_member_id,
                source_excerpt=item.get("source_excerpt"),
            )
            db.add(new_item)
            await db.flush()
            created += 1

            supersedes_id = item.get("supersedes_item_id")
            if supersedes_id:
                old = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.id == supersedes_id))).scalar_one_or_none()
                if old and old.id != new_item.id and _may_supersede(old, new_item):
                    old.is_current = False
                    old.superseded_by_id = new_item.id

    if latest_summary:
        newsletter.latest_summary = latest_summary
    dupe_note = f", {skipped_dupes} duplicate item(s) already covered" if skipped_dupes else ""
    total_chunks = -(-len(extractable_blocks) // _CHUNK_SIZE)  # ceil division
    if truncated_chunks:
        # Surfaced as a WARNING (not just appended text) so it's not lost in
        # a "success" status the way the original single-call version's
        # truncation note was - this is exactly the kind of partial-loss the
        # WARNING status exists to catch.
        truncated_note = (
            f"WARNING[llm_max_tokens]: {truncated_chunks} of {total_chunks} extraction batch(es) "
            "hit max_tokens (some items may be missing) · "
        )
    else:
        truncated_note = ""
    return f"{truncated_note}{vision_note}extracted {created} item(s){dupe_note}"
