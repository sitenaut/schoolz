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

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import scraper_client
from models import SmoreBlock, SmoreNewsletter

_HANDBOOK_RE = re.compile(r"handbook", re.IGNORECASE)
# Nav-link keyword -> SchoolDocument.doc_type. Handbooks were the first
# case; bell schedules were added after confirming both high schools
# publish theirs the same way (a nav page whose only content is a PDF link:
# west.chclc.org/our-school/chw-bell-schedule, east.chclc.org/our-school/
# bell-schedule). First match wins, so keep the more specific ones first.
_DOC_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bell_schedule", re.compile(r"bell[\s-]*schedule", re.IGNORECASE)),
    ("handbook", _HANDBOOK_RE),
]


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
        href = a["href"]
        doc_type = classify_doc_type(text) or classify_doc_type(href)
        if doc_type:
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            results.append({"title": text or doc_type.replace("_", " ").title(), "url": href, "doc_type": doc_type})
    return results


def _find_doc_file_links(html: str, base_url: str) -> list[str]:
    # Confirmed real: Finalsite wraps each page's actual content in
    # <main id="fsPageContent"> - restricting to it (falling back to the
    # whole page if that container isn't found) avoids picking up shared
    # nav/footer links repeated on every page (e.g. one district-wide drive
    # link that has nothing to do with this school's handbook).
    soup = BeautifulSoup(html, "lxml")
    container = soup.find(id="fsPageContent") or soup
    links = []
    for a in container.find_all("a", href=True):
        href = a["href"]
        if _DOC_FILE_RE.search(href):
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            links.append(href)
    return links


async def discover_from_website(school_website_url: str) -> list[dict]:
    """Follows any nav link mentioning "handbook" from the homepage, then
    looks one level deeper for the actual PDF/Google Doc link on that page
    - some schools' handbook nav item goes straight to a file, others go to
    a landing page that itself links out to the real document."""
    base = school_website_url.rstrip("/")
    # Deliberately NOT caught here (unlike the per-candidate follow-up fetch
    # below): if the homepage itself won't load, that's a real fetch
    # failure worth a classified error_code and traceback (see
    # scheduler/errors.py), not a silent empty list that reads identically
    # to "loaded fine, no handbook link" - that ambiguity was the actual
    # bug a real user hit (a warning with no way to tell what was checked).
    home = await scraper_client.fetch_html(base + "/", wait_for_selector="a")

    results = []
    seen_urls: set[str] = set()
    for candidate in _find_doc_anchors(home["html"], base):
        url = candidate["url"]
        doc_type = candidate["doc_type"]
        if _DOC_FILE_RE.search(url):
            if url not in seen_urls:
                seen_urls.add(url)
                results.append({"title": candidate["title"], "url": url, "academic_year": _extract_year(candidate["title"] + " " + url), "doc_type": doc_type})
            continue

        try:
            page = await scraper_client.fetch_html(url, wait_for_selector="a")
        except Exception:
            continue

        page_html = page["html"]
        page_title = page.get("title") or candidate["title"]
        doc_links = _find_doc_file_links(page_html, base)
        year = _extract_year(page_title) or _extract_year(page_html[:5000])
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
