"""Parses a school's own year-at-a-glance events calendar published as a
Google Doc - confirmed real on Cherry Hill West, whose activities site
(sites.google.com/chclc.org/chwstudentactivities/home) embeds a one-page
"West Calendar 2026-27" doc. West has no Smore newsletter, public Google
Calendar, or announcements doc, so this is the only place its school-wide
events (Back to School Night, concerts, Homecoming, Prom, Graduation) are
published at all. Google Sites renders the embed client-side, which is why
the activities-site crawl never saw any of it.

Parsed deterministically, no model call: every line carries its own date
("Apr. 20- Evening of Jazz (7pm)"), which matters because the doc is laid
out in three columns and its plain-text export interleaves them - line
order and the month header lines are meaningless, only each line's own
date is trustworthy.

Unlike the activities-site/announcements sources these items are
school-wide, not class-level detail, so the source is deliberately NOT in
CLASS_PAGE_SOURCES: they show on the school page and the general calendar.

Lines the district calendar already owns are skipped rather than
duplicated: closures/half-days (is_status_title), breaks, and first/last
day of school. Month-only lines ("Dec. - FAFSA (7pm)") are skipped too -
"sometime in December" can't sit on a calendar day, and picking one would
be a guess. The doc says "All dates are subject to change", so a scan
deletes rows whose line disappeared (same as hs_rotation).
"""

import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolContentItem
from scheduler.errors import record_parse_issue
from services.class_years import academic_year_start
from services.hs_announcements import doc_export_url
from services.school_status import is_status_title

logger = logging.getLogger(__name__)

SOURCE = "school_events_doc"
_JOB_KIND = "school_events_doc.scan"
_ET = ZoneInfo("America/New_York")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
# Date spec, then a dash followed by whitespace, then the title. A range's
# own dash never has whitespace after it ("10-11", "24-Jan. 3"), which is
# what tells it apart from the separator ("Sept. 10-11 - Underclassmen").
_LINE_RE = re.compile(r"^(?P<spec>[A-Za-z]{3,9}\.?[\s\d.,A-Za-z-]*?)\s*[-–]\s+(?P<title>\S.*)$")
_PART_RE = re.compile(r"^\s*(?:(?P<month>[A-Za-z]{3,9})\s*)?(?P<day>\d{1,2})?\s*$")
# Only a single plain time becomes a timed event - "(9-11:30am)" or
# "(12-2pm; 5-7pm)" stay in the title of an all-day row rather than being
# half-understood.
_TIME_RE = re.compile(r"\s*\((\d{1,2})(?::(\d{2}))?\s*(am|pm)\)\s*$", re.I)
_YEAR_RE = re.compile(r"\b(20\d{2})\s*[-–/]\s*(\d{2}|20\d{2})\b")
_DISTRICT_OWNED_RE = re.compile(r"\bbreak\b|\b(first|last)\s+day\s+of\s+school\b", re.I)


def _month(word: str | None) -> int | None:
    return _MONTHS.get(word.lower()) if word else None


def _parse_spec(spec: str) -> list[tuple[tuple[int, int], tuple[int, int]]] | None:
    """"Oct. 12, 14, 15" -> three single days; "Mar. 12-14, 19-21" -> two
    ranges; "Dec. 24-Jan. 3" -> one range crossing a month. Returns
    [((month, day), (month, day)), ...] with inclusive ends, or None when
    any part has no day number (a month-only line)."""
    current = None
    out = []
    for seg in spec.replace(".", " ").split(","):
        if not seg.strip():
            continue
        ends = []
        for part in seg.split("-"):
            m = _PART_RE.match(part)
            if not m or not m.group("day"):
                return None
            if m.group("month"):
                current = _month(m.group("month"))
            if current is None:
                return None
            ends.append((current, int(m.group("day"))))
        if len(ends) > 2:
            return None
        out.append((ends[0], ends[-1]))
    return out or None


def _year_for(month: int, start_year: int) -> int:
    return start_year if month >= 7 else start_year + 1


def parse_events_doc(text: str, fallback_start_year: int | None = None) -> tuple[list[dict], dict]:
    """Returns (events, stats). Each event: {title, start_date, end_date,
    is_all_day, line}. The academic year comes from the doc's own title
    ("West Calendar 2026-27"), falling back to the current school year."""
    text = text.lstrip("﻿")
    head = "\n".join(text.splitlines()[:3])
    ym = _YEAR_RE.search(head)
    start_year = int(ym.group(1)) if ym else (fallback_start_year or academic_year_start())

    events: list[dict] = []
    stats = {"skipped_district_owned": 0, "skipped_undated": 0, "unparsed": []}
    for raw in text.splitlines():
        line = raw.strip()
        m = _LINE_RE.match(line)
        if not m or _month(m.group("spec").split(".")[0].split()[0]) is None:
            continue  # month header, the doc's title/boilerplate, or a blank line
        title = m.group("title").strip()
        if is_status_title(title) or _DISTRICT_OWNED_RE.search(title):
            stats["skipped_district_owned"] += 1
            continue
        spans = _parse_spec(m.group("spec"))
        if spans is None:
            # Month-only ("Dec. - FAFSA") parses its month fine but no day.
            if re.fullmatch(r"[A-Za-z]{3,9}\.?", m.group("spec").strip()):
                stats["skipped_undated"] += 1
            else:
                stats["unparsed"].append(line)
            continue

        at = None
        tm = _TIME_RE.search(title)
        if tm:
            hour = int(tm.group(1)) % 12 + (12 if tm.group(3).lower() == "pm" else 0)
            at = time(hour, int(tm.group(2) or 0))
            title = title[: tm.start()].strip()

        try:
            for (sm, sd), (em, ed) in spans:
                first = date(_year_for(sm, start_year), sm, sd)
                last = date(_year_for(em, start_year), em, ed)
                if last < first:
                    raise ValueError("range ends before it starts")
                if at is not None:
                    # "Feb. 17-18- Pop Concert (7pm)" is two 7pm
                    # performances, not one 24-hour-plus event.
                    d = first
                    while d <= last:
                        events.append({"title": title, "start_date": datetime.combine(d, at, _ET), "end_date": None, "is_all_day": False, "line": line})
                        d += timedelta(days=1)
                else:
                    # All-day multi-day rows use the ICS exclusive end date,
                    # same as every other source (school_today._item_date_range).
                    events.append(
                        {
                            "title": title,
                            "start_date": datetime.combine(first, time(0), _ET),
                            "end_date": datetime.combine(last + timedelta(days=1), time(0), _ET) if last > first else None,
                            "is_all_day": True,
                            "line": line,
                        }
                    )
        except ValueError:
            stats["unparsed"].append(line)
    return events, stats


def _uid(title: str, start: datetime) -> str:
    digest = hashlib.sha1(f"{title.strip().lower()}|{start.isoformat()}".encode("utf-8")).hexdigest()[:20]
    return f"events_doc:{digest}"


async def scan_events_doc(db: AsyncSession, school: School) -> str:
    if not school.events_doc_url:
        return "no events_doc_url configured"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(doc_export_url(school.events_doc_url), headers={"User-Agent": "schoolz-events-doc/1.0"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("school_events_doc_fetch_failed", extra={"school_id": school.id, "error": str(exc)})
            return f"WARNING[fetch_failed]: could not fetch events doc: {exc}"
        # Google's txt export is UTF-8 but doesn't always say so, and httpx
        # would then guess latin-1 ("Lion’s" -> "LionÃ¢Â€Â™s").
        resp.encoding = "utf-8"
        text = resp.text

    events, stats = parse_events_doc(text)
    for line in stats["unparsed"]:
        record_parse_issue(_JOB_KIND, "unexpected_format", school_id=school.id, sample=line[:200])
    if not events:
        # Never prune on an empty parse - a doc that got restructured
        # shouldn't silently wipe every event already on the calendar.
        return "WARNING[no_events]: no dated event lines found in the doc"

    existing = {
        r.external_uid: r
        for r in (
            await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id, SchoolContentItem.source == SOURCE))
        ).scalars()
    }
    seen: set[str] = set()
    created = updated = 0
    for ev in events:
        uid = _uid(ev["title"], ev["start_date"])
        if uid in seen:
            continue
        seen.add(uid)
        row = existing.get(uid)
        if row is None:
            row = SchoolContentItem(scope="school", school_id=school.id, source=SOURCE, external_uid=uid, category="event")
            db.add(row)
            created += 1
        else:
            updated += 1
        row.title = ev["title"][:300]
        row.start_date = ev["start_date"]
        row.end_date = ev["end_date"]
        row.is_all_day = ev["is_all_day"]
        row.link_url = school.events_doc_url
        row.source_excerpt = ev["line"]
        row.is_current = True

    removed = 0
    for uid, row in existing.items():
        if uid not in seen:
            await db.delete(row)
            removed += 1
    await db.flush()

    summary = (
        f"events doc: {len(seen)} event(s) - {created} created, {updated} updated, {removed} removed; "
        f"skipped {stats['skipped_district_owned']} district-owned and {stats['skipped_undated']} month-only line(s)"
    )
    if stats["unparsed"]:
        return f"WARNING[unparsed_lines]: {summary}; {len(stats['unparsed'])} line(s) not understood"
    return summary
