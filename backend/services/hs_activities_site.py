"""Crawls a high school's own Google Sites "activities" microsite (Cherry
Hill East's confirmed real: sites.google.com/chclc.org/cheactivities) and
turns each page into structured SchoolContentItem rows, grad-year-tagged.

Deliberately no Playwright/the scraper service: Google Sites server-renders
its pages, so a plain httpx GET gets everything a browser would - keeping
these ~20 page fetches off the 12h burst's shared 1GB Chromium (see
CLAUDE.md's "The 12h cron is a burst"). Confirmed by fetching the real site
this way during design (docs/HS_CLASS_PAGES_DESIGN.md).

The one non-obvious parsing trap this module exists to handle: Google
Sites splits inline text across many separate DOM text nodes with NO
whitespace between them at the split point - "$750.00" arrives as three
separate strings ("$7", "5", "0.00") and "Class of 2027" arrives as
("Class of 202", "7"). A naive `.get_text(" ")` (or any tag->newline
regex) inserts a separator at every one of those splits and mangles every
number and year on the page. The fix is `_own_block_text()`: join text
WITHIN one block-level element with no separator (recovers the original,
un-split string, since Sites never puts real whitespace at a intra-word
split point) and only separate BETWEEN block-level elements.

Attribution is resolved deterministically from the page's own URL before
any model call: a `.../class-of-2027` (or a sub-page under it) sets
applies_to_grad_years=[2027] on every item extracted from that page. This
is the one piece of this pipeline that would be worst as an LLM guess and
is instead a regex against a URL Google Sites itself already encodes the
answer into.
"""

import hashlib
import logging
import os
import re
import time
from urllib.parse import urljoin, urlsplit

import httpx
from anthropic import AsyncAnthropic
from bs4 import BeautifulSoup, NavigableString, Tag
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import observability
from models import School, SchoolClassYear, SchoolContentItem, StaffMember, normalize_name
from scheduler.errors import record_parse_issue
from services.class_years import default_label, get_or_create_class_year
from services.content_extractor import ANTHROPIC_API_KEY, MODEL, _parse_date
from services.links import unwrap_redirect

logger = logging.getLogger(__name__)

_JOB_KIND = "hs_activities_site.scan"

_BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "blockquote", "figcaption"}

# Fragment-only links (Google Sites' own in-page nav anchors, "#h.xxxx")
# and a page's own site-relative nav links aren't real content links -
# never worth surfacing as an item's link_url.
_SKIP_LINK_RE = re.compile(r"^#|^/chclc\.org/cheactivities/?$", re.IGNORECASE)

_GRAD_YEAR_PATH_RE = re.compile(r"class-of-(\d{4})", re.IGNORECASE)

# Deliberately excluded per explicit product call (see
# docs/HS_CLASS_PAGES_DESIGN.md ~Tier 5): archive/historical content with
# no current-year relevance. Matched against the page's path.
_SKIP_PATH_RE = re.compile(r"senior-hall-of-fame|past-disney-trips|sga/\d{4}-\d{2}-sga-officers|spirit-week-\d{4}", re.IGNORECASE)


def grad_years_from_path(path: str) -> list[int] | None:
    m = _GRAD_YEAR_PATH_RE.search(path)
    return [int(m.group(1))] if m else None


def _own_block_text(el: Tag) -> tuple[str, str | None] | None:
    """This block's own text with NO separator (see module docstring),
    stopping at any nested block-level descendant rather than skipping the
    whole element when one exists.

    A first version here skipped any block with a nested block-tag
    descendant ANYWHERE inside it, to avoid emitting the same text twice
    for a <div> wrapping a <p>. That silently dropped real content:
    confirmed on Cherry Hill East's own class-of-2027 page, whose "Grade
    Level Principal: Mrs. Kate Pereira" and "ADVISOR: Dr. Kathy Lewis"
    lines sit as loose text directly inside a <div> that ALSO happens to
    contain other block elements elsewhere - not wrapping them, just a
    sibling. That one shared ancestor was enough to discard the whole
    block's own text, and the entire page came back with nothing but nav
    links and the footer contact line. Recursing only into inline
    (non-block) descendants, and simply not re-descending into a nested
    block tag (it gets visited separately, in its own right, by the outer
    find_all) fixes this without the double-emit the first version was
    guarding against."""
    parts: list[str] = []
    link: str | None = None

    def walk(node: Tag) -> None:
        nonlocal link
        for child in node.children:
            if isinstance(child, NavigableString):
                if str(child).strip():
                    parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name in _BLOCK_TAGS:
                    continue  # its own text belongs to ITS OWN emission
                if link is None and child.name == "a" and child.get("href"):
                    href = child["href"].strip()
                    if href and not _SKIP_LINK_RE.match(href):
                        link = unwrap_redirect(href)
                walk(child)

    walk(el)
    text = "".join(parts).strip()
    return (text, link) if text else None


def _iter_blocks(soup: BeautifulSoup):
    yield from soup.find_all(_BLOCK_TAGS)


async def _fetch(url: str, client: httpx.AsyncClient) -> BeautifulSoup | None:
    try:
        resp = await client.get(url, headers={"User-Agent": "schoolz-hs-activities-site/1.0"})
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("hs_activities_site_fetch_failed", extra={"url": url, "error": str(exc)})
        record_parse_issue(_JOB_KIND, "fetch_failed", url=url, sample=str(exc)[:200])
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    return soup


async def discover_pages(base_url: str, client: httpx.AsyncClient) -> list[str]:
    """The site's own nav renders on every page (confirmed real), so one
    fetch of the home page yields every sub-page path - no sitemap or API
    needed."""
    soup = await _fetch(base_url, client)
    if soup is None:
        return [base_url]
    split = urlsplit(base_url)
    # e.g. "/chclc.org/cheactivities" - everything before the site's own
    # last path segment ("/home"), which is what every real sub-page's
    # href shares as a prefix.
    base_path_prefix = "/" + "/".join(split.path.strip("/").split("/")[:-1])

    seen: dict[str, None] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if _SKIP_LINK_RE.match(href) or not href.startswith(base_path_prefix):
            continue
        abs_url = urljoin(base_url, href)
        if _SKIP_PATH_RE.search(abs_url):
            continue
        seen[abs_url.split("#")[0]] = None
    if base_url not in seen:
        seen[base_url] = None
    return list(seen.keys())


def build_corpus(soup: BeautifulSoup) -> list[str]:
    """One line per leaf content block, in the same "(link: ...)" shape as
    content_extractor.py's newsletter corpus - so the extraction prompt
    below can reuse its exact "always copy the link" instruction."""
    lines: list[str] = []
    seen_text: set[str] = set()
    for el in _iter_blocks(soup):
        result = _own_block_text(el)
        if result is None:
            continue
        text, link = result
        # Every page repeats the full site nav (confirmed real: ~40 lines
        # of "Home / CLUBS / Class of 2027 / ..." on every single page) -
        # drop exact repeats of a block already seen on THIS page, which
        # catches the nav without needing to hand-identify its markup.
        if text in seen_text:
            continue
        seen_text.add(text)
        suffix = f" (link: {link})" if link else ""
        lines.append(f"{text}{suffix}")
    return lines


_EXTRACTION_TOOL = {
    "name": "record_page_extraction",
    "description": "Records structured items extracted from one page of a high school's activities/class website.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["event", "deadline", "initiative", "reminder", "policy_change", "procedure", "program", "org_club", "person"],
                        },
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "start_date": {"type": "string", "description": "'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS', school-local time, no timezone offset. Omit if no real date is given."},
                        "end_date": {"type": "string"},
                        "link_url": {"type": "string", "description": "Copy from a '(link: ...)' annotation when the item is based on that block - never drop a link that's present in the source."},
                        "person_name": {"type": "string"},
                        "person_title": {"type": "string"},
                        # Only meaningfully different from the page's own
                        # URL-derived grad year on a page that explicitly
                        # names a narrower or wider audience than "this
                        # whole class" (e.g. "open to 10th through 12th
                        # graders", or a picture-day page that's really
                        # about two specific classes) - otherwise omit and
                        # the page's own attribution applies.
                        "audience_grad_years": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["category", "title"],
                },
            },
            # Populated ONLY when this page is itself a class's home page
            # (e.g. .../class-of-2027, not a sub-page under it) and names
            # the class's own people/social links - omitted entirely on
            # every other page.
            "class_year_facts": {
                "type": "object",
                "properties": {
                    "grade_level_principal_names": {"type": "array", "items": {"type": "string"}},
                    "advisor_names": {"type": "array", "items": {"type": "string"}},
                    "instagram_url": {"type": "string"},
                },
            },
        },
        "required": ["items"],
    },
}

_SYSTEM_PROMPT = """You extract structured information from one page of a high school's student-activities \
website, for parents. Extract EVERY distinct fact worth a parent knowing: dates, deadlines, procedures, \
payment/cost information, contact people, and club/program info. Completeness matters more than brevity - \
do not summarize multiple distinct facts into one combined item. \
Ignore any image/photo content entirely - this page's images are not meant to be transcribed or described, \
only its text. \
Every link mentioned in the source (marked "(link: ...)") must be preserved - if an item is based on a \
block with a link annotation, copy that URL into the item's link_url field. Never drop a link that's present \
in the source. \
Dates should be resolved to actual ISO 8601 dates when the text gives enough context (a year stated \
elsewhere on the page, or the page's own dateline); omit start_date/end_date if you can't determine an \
actual date - never guess a year. \
For category='person', title MUST be the person's actual name, with their role in person_title - never put \
a role/title in title instead of a name. \
Only set class_year_facts if this page is itself introducing one class's own people/social links (grade \
level principal, class advisors, class Instagram) - omit it entirely on every other page, including a class's \
own sub-pages (parking, portraits, trip payment schedule, etc), which should only produce ordinary items."""


def _stable_uid(page_path: str, title: str, start_date_iso: str | None) -> str:
    digest = hashlib.sha1(f"{title}|{start_date_iso or ''}".encode("utf-8")).hexdigest()[:20]
    return f"site:{page_path}:{digest}"


async def _resolve_class_year_facts(db: AsyncSession, school_id: str, grad_year: int, facts: dict, page_url: str, staff_by_name: dict[str, str]) -> None:
    """Ambiguous/no match against the roster resolves to no id, never a
    guess - same rule as SchoolContentItem.staff_member_id resolution in
    content_extractor.py. Never overwrites a field an admin already set
    (SchoolClassYearUpdate) - only fills what's currently empty, same
    "never overwrite, only backfill" rule content_extractor uses for
    duplicate descriptions."""
    class_year = await get_or_create_class_year(db, school_id, grad_year)

    def resolve_names(names: list[str] | None) -> list[str] | None:
        if not names:
            return None
        ids = [staff_by_name[normalize_name(n)] for n in names if normalize_name(n) in staff_by_name]
        return ids or None

    if class_year.grade_level_principal_staff_ids is None:
        class_year.grade_level_principal_staff_ids = resolve_names(facts.get("grade_level_principal_names"))
    if class_year.advisor_staff_ids is None:
        class_year.advisor_staff_ids = resolve_names(facts.get("advisor_names"))
    if not class_year.instagram_url and facts.get("instagram_url"):
        class_year.instagram_url = facts["instagram_url"]
    if not class_year.label:
        class_year.label = default_label(grad_year)
    class_year.source_page_url = page_url


async def scan_activities_site(db: AsyncSession, school: School) -> str:
    if not ANTHROPIC_API_KEY:
        return "skipped - ANTHROPIC_API_KEY not configured"
    if not school.activities_site_url:
        return "no activities_site_url configured"

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    staff_result = await db.execute(select(StaffMember).where(StaffMember.school_id == school.id))
    staff_by_name = {normalize_name(s.full_name): s.id for s in staff_result.scalars().all()}

    existing_by_uid = {
        row.external_uid: row
        for row in (
            await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.school_id == school.id,
                    SchoolContentItem.source == "hs_activities_site",
                    SchoolContentItem.external_uid.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    }

    pages_scanned = 0
    items_created = items_updated = 0
    truncated = 0
    touched_uids: set[str] = set()

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as http_client:
        page_urls = await discover_pages(school.activities_site_url, http_client)
        for page_url in page_urls:
            soup = await _fetch(page_url, http_client)
            if soup is None:
                continue
            pages_scanned += 1
            corpus_lines = build_corpus(soup)
            if not corpus_lines:
                continue

            page_path = urlsplit(page_url).path
            page_grad_years = grad_years_from_path(page_path)
            # A page IS a class's home page (not a sub-page under it) when
            # its own path ends in the class-of-YYYY segment.
            is_class_home_page = bool(re.search(r"class-of-\d{4}/?$", page_path, re.IGNORECASE))

            _llm_started = time.perf_counter()
            response = await client.messages.create(
                model=MODEL,
                max_tokens=4096,
                temperature=0,
                system=_SYSTEM_PROMPT,
                tools=[_EXTRACTION_TOOL],
                tool_choice={"type": "tool", "name": "record_page_extraction"},
                messages=[{"role": "user", "content": "\n".join(corpus_lines)}],
            )
            observability.record_llm_call("hs_activities_site_extract", MODEL, response, time.perf_counter() - _llm_started)
            tool_use = next((b for b in response.content if b.type == "tool_use"), None)
            if not tool_use:
                continue
            data = tool_use.input
            if response.stop_reason == "max_tokens":
                truncated += 1
                record_parse_issue(_JOB_KIND, "llm_max_tokens", url=page_url)

            if is_class_home_page and page_grad_years:
                # Always visited (sets source_page_url/label) even when the
                # model found no names/Instagram worth reporting this run -
                # a sparse page (confirmed real: East's own class-of-2027
                # page is a handful of short lines) shouldn't leave
                # provenance null just because extraction came up empty.
                await _resolve_class_year_facts(db, school.id, page_grad_years[0], data.get("class_year_facts") or {}, page_url, staff_by_name)

            for item in data.get("items", []):
                # "required" in a tool schema is a hint the model usually
                # follows, not a guarantee the API enforces - confirmed
                # real: an item came back with no title at all, and a bare
                # item["title"] here crashed the whole run (and every item
                # after it in the same page) rather than just skipping one
                # bad item.
                title = item.get("title")
                category = item.get("category")
                if not title or not category:
                    record_parse_issue(_JOB_KIND, "unexpected_format", url=page_url, sample=str(item)[:200])
                    continue

                grad_years = item.get("audience_grad_years") or page_grad_years
                start_date = _parse_date(item.get("start_date"))
                end_date = _parse_date(item.get("end_date"))
                uid = _stable_uid(page_path, title, item.get("start_date"))
                touched_uids.add(uid)

                row = existing_by_uid.get(uid)
                if row is None:
                    row = SchoolContentItem(scope="school", school_id=school.id, source="hs_activities_site", external_uid=uid)
                    db.add(row)
                    existing_by_uid[uid] = row
                    items_created += 1
                else:
                    items_updated += 1

                row.category = category
                row.title = title[:300]
                row.description = item.get("description")
                row.start_date = start_date
                row.end_date = end_date
                row.is_all_day = "T" not in (item.get("start_date") or "")
                row.link_url = unwrap_redirect(item.get("link_url"))
                row.person_name = item.get("person_name")
                row.person_title = item.get("person_title")
                row.applies_to_grad_years = grad_years
                row.source_excerpt = "\n".join(corpus_lines)[:1000]
                name_candidates = [n for n in (item.get("person_name"), title if category == "person" else None) if n]
                row.staff_member_id = next((staff_by_name[normalize_name(n)] for n in name_candidates if normalize_name(n) in staff_by_name), None)

    # Retire whatever a full crawl no longer produces - confirmed real: a
    # corpus-extraction fix landed between two scans, the second run's
    # richer text produced better-titled items for content the first run
    # had already (imperfectly) extracted, and the first run's items had
    # no mechanism to ever go away - 232 stale rows piled up alongside 125
    # fresh ones with nothing to tell them apart, and a class page that
    # should have ~50 items rendered over 300. Only when every discovered
    # page was actually fetched this run, never on a partial crawl (a
    # network hiccup on one page must not retire that page's real,
    # still-true content just because this run didn't re-touch it).
    retired = 0
    if page_urls and pages_scanned == len(page_urls):
        stale = [row for uid, row in existing_by_uid.items() if uid not in touched_uids and row.is_current]
        for row in stale:
            row.is_current = False
        retired = len(stale)

    await db.flush()
    warn = f"WARNING[llm_max_tokens]: {truncated} page(s) truncated · " if truncated else ""
    retired_note = f", {retired} retired" if retired else ""
    return f"{warn}activities site: {pages_scanned} page(s) scanned, {items_created} item(s) created, {items_updated} updated{retired_note}"
