"""Discovers reference documents (parent/student handbooks, to start) for a
school. Unlike LunchMenu, there's no one reliable filename/URL pattern here
- confirmed real variance across Cherry Hill schools:

- Some schools link a handbook page directly from their own site nav
  (slugs vary: "parent-student-handbook-2023-2024", "family-handbook/home",
  "parentstudent-handbook/home") - that landing page then usually links out
  to the actual PDF/Google Doc.
- Others (confirmed: Beck, Rosa, Knight) have no handbook page on their site
  at all - their current handbook only shows up as a Google Doc link buried
  inside a Smore newsletter block's text (including OCR'd text from an
  image block), never a discrete anchor tag.

So discovery tries the site first, then falls back to scanning this
school's already-extracted Smore blocks for a "handbook" mention. Both
paths try to parse an academic year (e.g. "2026-2027") out of the title/
link/surrounding text specifically so a newer year can be preferred over a
stale one - confirmed real case: a school's own site nav links a page still
labeled 2023-2024 while its current newsletter links a 2026-2027 version.
"""

import re
import time
from datetime import date
from urllib.parse import unquote, urljoin

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import scraper_client
from models import SmoreBlock, SmoreNewsletter
from services.presence_documents import list_page_documents

_HANDBOOK_RE = re.compile(r"handbook", re.IGNORECASE)
_PRESENCE_RE = re.compile(r"sharpschool\.com|SchoolMessenger Presence", re.IGNORECASE)
# Nav-link keyword -> SchoolDocument.doc_type. Handbooks were the first
# case; bell schedules were added after confirming both high schools
# publish theirs the same way (a nav page whose only content is a PDF link:
# west.chclc.org/our-school/chw-bell-schedule, east.chclc.org/our-school/
# bell-schedule). First match wins, so keep the more specific ones first.
_DOC_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Medford's home page links its A-D rotation calendar as "What Day is It?".
    ("letter_day_schedule", re.compile(r"what\s+day\s+is\s+it|\d\s*-?\s*day\s+cycle", re.IGNORECASE)),
    ("bell_schedule", re.compile(r"bell[\s-]*schedule", re.IGNORECASE)),
    ("handbook", _HANDBOOK_RE),
]


# A "District Calendars" page (Medford Lakes) is a hub: its district-calendar and
# trimester PDFs aren't documents we keep, but its "6 Day Cycle Calendar" is.
_POLICY_NAV_RE = re.compile(r"polic(?:y|ies)", re.IGNORECASE)
_FAMILY_NAV_RE = re.compile(r"parent|student|family", re.IGNORECASE)
_CALENDAR_HUB_RE = re.compile(r"^district\s+calendars?$", re.IGNORECASE)


# A school-lunch ordering portal linked from the home page. FoodDays is a
# login-only app with no public menu, so all there is to keep is the link.
_ORDERING_PORTAL_RE = re.compile(r"^https?://(?:[\w-]+\.)*myfooddays\.com(?:/|$)", re.IGNORECASE)


def classify_doc_type(text: str) -> str | None:
    for doc_type, pattern in _DOC_TYPE_PATTERNS:
        if pattern.search(text):
            return doc_type
    return None
_YEAR_RE = re.compile(r"(20\d{2})\s*[-–]\s*(20\d{2})")
_SHORT_YEAR_RE = re.compile(r"(?<!\d)(2\d)\s*[-–]\s*(2\d)(?!\d)")
_URL_RE = re.compile(r"https?://\S+")
_DOC_FILE_RE = re.compile(r"\.pdf($|\?)|docs\.google\.com|drive\.google\.com", re.IGNORECASE)


def _extract_year(text: str) -> str | None:
    match = _YEAR_RE.search(text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    short = _SHORT_YEAR_RE.search(text)
    if short and int(short.group(2)) == int(short.group(1)) + 1:
        return f"20{short.group(1)}-20{short.group(2)}"
    return None


def _find_doc_anchors(html: str, base_url: str) -> list[dict]:
    # Site nav (which repeats on every page, e.g. a shared district-wide
    # drive link) can itself contain the word "handbook" via unrelated
    # items - anchors are only trusted from the homepage nav here, so this
    # stays unscoped; _find_doc_file_links (used on a *followed* landing
    # page) is the one that needs to avoid nav noise.
    soup = BeautifulSoup(html, "lxml")
    results = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"].strip()
        # "#", javascript:, mailto: and tel: are not pages. "#" used to be sent
        # to the scraper as a URL (9 failed renders per scan once retries and
        # fallbacks multiplied it), which tripped the residential error-ratio alert.
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        doc_type = (
            "lunch_ordering" if _ORDERING_PORTAL_RE.match(href)
            else classify_doc_type(text) or classify_doc_type(href) or ("calendar_hub" if _CALENDAR_HUB_RE.match(text) else None)
        )
        # A "Policy, Procedure and Handbook" nav page is a folder of board policies, not the handbook.
        if doc_type == "handbook" and _POLICY_NAV_RE.search(text) and not _FAMILY_NAV_RE.search(text):
            continue
        # Magnolia nests every policy page under /policieshibhandbook/..., so each child nav link matched on its href alone.
        if doc_type == "handbook" and not _HANDBOOK_RE.search(text) and _POLICY_NAV_RE.search(href):
            continue
        if doc_type:
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            results.append({"title": text or doc_type.replace("_", " ").title(), "url": href, "doc_type": doc_type})
    return results


def _find_doc_file_anchors(html: str, base_url: str) -> list[tuple[str, str]]:
    # Confirmed real: Finalsite wraps each page's actual content in
    # <main id="fsPageContent"> - restricting to it (falling back to the
    # whole page if that container isn't found) avoids picking up shared
    # nav/footer links repeated on every page (e.g. one district-wide drive
    # link that has nothing to do with this school's handbook).
    # Edlio's equivalent is #pageContentWrapper: unscoped, the "Handbook"
    # page picked up three unrelated /pdfs/ links from the site footer.
    soup = BeautifulSoup(html, "lxml")
    container = soup.find(id="fsPageContent") or soup.find(id="pageContentWrapper") or soup
    links = []
    for a in container.find_all("a", href=True):
        href = a["href"]
        if _DOC_FILE_RE.search(href):
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            links.append((href, a.get_text(" ", strip=True)))
    return links


def _find_doc_file_links(html: str, base_url: str) -> list[str]:
    return [href for href, _ in _find_doc_file_anchors(html, base_url)]


_NOT_A_SCHOOL_HANDBOOK_RE = re.compile(r"dyslexia", re.IGNORECASE)


def _find_eschoolview_handbooks(html: str) -> list[dict]:
    """eSchoolView/LINQ (Mount Laurel): every page carries the whole mega-menu,
    and the menu has no content container to scope to - following each
    "handbook" landing page produced 18 unrelated PDFs/forms for one school.
    The school's own handbook is a direct Google Doc/PDF link in its nav, so
    take only those and never crawl further."""
    seen: set[str] = set()
    results = []
    for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        if not _HANDBOOK_RE.search(text) or _NOT_A_SCHOOL_HANDBOOK_RE.search(text) or not _DOC_FILE_RE.search(href) or href in seen:
            continue
        seen.add(href)
        results.append({"title": text, "url": href, "academic_year": _extract_year(text + " " + href), "doc_type": "handbook"})
    return results


_LETTER_DAY_RE = re.compile(r"letter[\s-]*day", re.IGNORECASE)


def _find_letter_day_page(html: str, page_url: str) -> str | None:
    for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
        if _LETTER_DAY_RE.search(a.get_text(" ", strip=True)) and not _DOC_FILE_RE.search(a["href"]):
            return urljoin(page_url, a["href"])
    return None


def _find_letter_day_pdfs(html: str, page_url: str, today: date | None = None) -> list[dict]:
    """A letter-day article (Mount Laurel's Hillside: a 4-day A-D cycle) holds
    one calendar PDF per month, replaced as the year goes on. The article's
    own URL is what stays put, so it's found from the school's home page and
    only its "...Letter Day Schedule" files are kept. The letters are drawn
    into the image, so the PDF is linked, not parsed. A month has no year of
    its own, so the academic year comes from the title or today's date."""
    today = today or date.today()
    results, seen = [], set()
    for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
        text = re.sub(r"\.pdf$", "", a.get_text(" ", strip=True), flags=re.I).strip()
        href = urljoin(page_url, a["href"])
        if not _LETTER_DAY_RE.search(text) or not _DOC_FILE_RE.search(href) or href in seen:
            continue
        seen.add(href)
        explicit = re.search(r"(20\d{2})", text)
        start = int(explicit.group(1)) if explicit else today.year
        if not explicit and today.month < 7:
            start -= 1
        results.append({"title": text, "url": href, "academic_year": f"{start}-{start + 1}", "doc_type": "letter_day_schedule"})
    return results


def keep_own_school_bell_schedules(entries: list[dict], school_tokens: list[str]) -> tuple[list[dict], bool]:
    """Sister schools on one shared site (Medford Lakes) each get their own
    bell-schedule PDF, and the nav lists all of them. When some of the
    bell schedules name this school in their file name or title, keep only
    those; when none do (one schedule for everyone), keep them all. Returns
    (entries, filtered)."""
    tokens = [t.lower() for t in school_tokens if t]
    bells = [e for e in entries if e["doc_type"] == "bell_schedule"]
    own = [e for e in bells if any(t in unquote(e["url"] + " " + e["title"]).lower() for t in tokens)]
    if not own or len(own) == len(bells):
        return entries, False
    return [e for e in entries if e["doc_type"] != "bell_schedule" or e in own], True


def looks_like_file_download(headers: httpx.Headers) -> bool:
    """A nav link whose URL has no file extension can still serve the file
    itself - Lenape Regional's /students/student-handbook answers with the
    PDF. Rendered in Chromium, that's "Page.goto: Download is starting": the
    candidate was silently dropped, after nine failed renders across all
    three scrapers (enough to fire the residential scraper's failure-rate
    alert, 2026-10-03)."""
    if "attachment" in headers.get("content-disposition", "").lower():
        return True
    content_type = headers.get("content-type", "").split(";")[0].strip().lower()
    return bool(content_type) and content_type not in ("text/html", "application/xhtml+xml", "text/plain")


async def _is_file_download(url: str) -> bool:
    # Headers only (the body is never read), over plain HTTP - no browser.
    # Any failure means "not known to be a file", so the page render below
    # still gets its chance.
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as client:
            async with client.stream("GET", url) as resp:
                return resp.status_code == 200 and looks_like_file_download(resp.headers)
    except httpx.HTTPError:
        return False


async def discover_from_website(school_website_url: str) -> list[dict]:
    """Follows any nav link mentioning "handbook" from the homepage, then
    looks one level deeper for the actual PDF/Google Doc link on that page
    - some schools' handbook nav item goes straight to a file, others go to
    a landing page that itself links out to the real document."""
    base = school_website_url.rstrip("/")
    if base.lower().endswith(".aspx"):
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as client:
            resp = await client.get(base)
            resp.raise_for_status()
            found = _find_eschoolview_handbooks(resp.text)
            letter_page = _find_letter_day_page(resp.text, str(resp.url))
            if letter_page:
                article = await client.get(letter_page)
                if article.status_code == 200:
                    found += _find_letter_day_pdfs(article.text, str(article.url))
        return found
    # Deliberately NOT caught here (unlike the per-candidate follow-up fetch
    # below): if the homepage itself won't load, that's a real fetch
    # failure worth a classified error_code and traceback (see
    # scheduler/errors.py), not a silent empty list that reads identically
    # to "loaded fine, no handbook link" - that ambiguity was the actual
    # bug a real user hit (a warning with no way to tell what was checked).
    async def fetch(url, wait_for_selector=None):
        return await scraper_client.fetch_html(url, wait_for_selector=wait_for_selector, block_assets=True)
    presence = False
    # SchoolMessenger Presence (ex-SharpSchool: Sterling, Somerdale) answers plain HTTP, and
    # headless Chromium gets 502s from it (hung nav / ERR_ABORTED), so the scraper never loads.
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as probe:
        try:
            plain_home = await probe.get(base + "/")
        except httpx.HTTPError:
            plain_home = None
    if plain_home is not None and plain_home.status_code == 200 and _PRESENCE_RE.search(plain_home.text):
        presence = True

        async def fetch(url, wait_for_selector=None):
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                title = BeautifulSoup(resp.text, "lxml").title
                return {"html": resp.text, "title": title.get_text(strip=True) if title else None}

    home = await fetch(base + "/", wait_for_selector="a")

    results = []
    seen_urls: set[str] = set()
    for candidate in _find_doc_anchors(home["html"], base):
        url = candidate["url"]
        doc_type = candidate["doc_type"]
        if doc_type == "lunch_ordering":
            if url not in seen_urls:
                seen_urls.add(url)
                results.append({"title": candidate["title"], "url": url, "academic_year": None, "doc_type": doc_type})
            continue
        if _DOC_FILE_RE.search(url):
            if url not in seen_urls:
                seen_urls.add(url)
                results.append({"title": candidate["title"], "url": url, "academic_year": _extract_year(candidate["title"] + " " + url), "doc_type": doc_type})
            continue

        if await _is_file_download(url):
            if url not in seen_urls:
                seen_urls.add(url)
                results.append({"title": candidate["title"], "url": url, "academic_year": _extract_year(candidate["title"] + " " + url), "doc_type": doc_type})
            continue

        try:
            page = await fetch(url, wait_for_selector="a")
        except Exception:
            continue

        page_html = page["html"]
        page_title = page.get("title") or candidate["title"]
        if doc_type == "calendar_hub":
            for doc_url, text in _find_doc_file_anchors(page_html, base):
                if classify_doc_type(text) == "letter_day_schedule" and doc_url not in seen_urls:
                    seen_urls.add(doc_url)
                    clean = re.sub(r"\.pdf$", "", re.sub(r"\s+", " ", text), flags=re.I).strip(" -")
                    results.append({"title": clean, "url": doc_url, "academic_year": _extract_year(text + " " + doc_url), "doc_type": "letter_day_schedule"})
            continue
        doc_links = _find_doc_file_links(page_html, base)
        year = _extract_year(page_title) or _extract_year(page_html[:5000])
        if presence and not doc_links:
            # A Presence page's files live in a documents widget the static HTML
            # never contains; use the ones whose own title says what we're after.
            try:
                widget_docs = [d for d in await list_page_documents(url) if classify_doc_type(d["title"]) == doc_type]
            except httpx.HTTPError:
                widget_docs = []
            for d in widget_docs[:1]:
                if d["url"] not in seen_urls:
                    seen_urls.add(d["url"])
                    results.append({"title": d["title"], "url": d["url"], "academic_year": _extract_year(d["title"]) or year, "doc_type": doc_type})
            if widget_docs:
                continue
        if doc_links:
            for doc_url in doc_links:
                if doc_url not in seen_urls:
                    seen_urls.add(doc_url)
                    # The year often lives only in the file name
                    # (WestBellSchedule26-27.pdf) - fall back to the URL.
                    results.append({"title": page_title, "url": doc_url, "academic_year": year or _extract_year(doc_url), "doc_type": doc_type})
        elif url not in seen_urls:
            # No standalone file found on the landing page - link to the
            # page itself so there's still something to click through to.
            seen_urls.add(url)
            results.append({"title": page_title, "url": url, "academic_year": year, "doc_type": doc_type})

    return results


_DISTRICT_HOME_CACHE: dict[str, tuple[float, list[dict]]] = {}
_DISTRICT_HOME_TTL_S = 6 * 3600


async def discover_district_letter_days(district_website_url: str, today: date | None = None) -> list[dict]:
    """A district-wide rotation calendar linked only from the district home page
    (Medford's "What Day is It?" Drive file; the file id changes when the sheet
    is replaced, so the link text is what's tracked). The doc has no year of
    its own, so it gets the academic year `today` falls in."""
    today = today or date.today()
    start = today.year if today.month >= 7 else today.year - 1
    # Every elementary school of a district asks for the same page; render it once per window.
    cached = _DISTRICT_HOME_CACHE.get(district_website_url)
    if cached and time.monotonic() - cached[0] < _DISTRICT_HOME_TTL_S:
        docs = cached[1]
    else:
        docs = [d for d in await discover_from_website(district_website_url) if d["doc_type"] == "letter_day_schedule"]
        _DISTRICT_HOME_CACHE[district_website_url] = (time.monotonic(), docs)
    return [{**d, "academic_year": d["academic_year"] or f"{start}-{start + 1}"} for d in docs]


async def discover_from_smore(db: AsyncSession, school_id: str) -> list[dict]:
    rows = (
        await db.execute(
            select(SmoreBlock).join(SmoreNewsletter, SmoreNewsletter.id == SmoreBlock.newsletter_id).where(SmoreNewsletter.school_id == school_id)
        )
    ).scalars().all()

    results = []
    seen_urls: set[str] = set()
    for block in rows:
        combined = " ".join(filter(None, [block.text_content, block.vision_extracted_text]))
        if not _HANDBOOK_RE.search(combined):
            continue
        year = _extract_year(combined)
        for url in _URL_RE.findall(combined):
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = f"{year} Parent/Student Handbook" if year else "Parent/Student Handbook"
            results.append({"title": title, "url": url, "academic_year": year, "doc_type": "handbook"})
    return results
