"""Parses the district's "Conferences, Interim and Report Card Dates" page
into structured per-school-type deadlines. Deliberately a plain HTML table
parser, not an LLM extraction pass - confirmed real: the page renders these
as genuine `<table>` elements with a clean header row (e.g. "Interims
Issued" / "Marking Period Ends" / "Report Card Dates"), one table per
school tier (High School, Middle School, Grades K-5, Preschool), preceded
by an all-caps `<p>` heading naming the tier - reliable enough to parse
deterministically rather than risk an LLM mis-zipping which date belongs
to which column.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

import scraper_client
from scheduler.errors import record_parse_issue

_ET = ZoneInfo("America/New_York")

# Maps the page's own all-caps section heading to School.school_type -
# whichever heading most recently preceded a <table> in document order.
_HEADING_TO_SCHOOL_TYPE = {
    "HIGH SCHOOL": "high",
    "MIDDLE SCHOOL": "middle",
    "GRADES K-5 INTERIM AND REPORT CARD SCHEDULE": "elementary",
    "PRESCHOOL REPORT CARD SCHEDULE": "other",
}

_SCHOOL_TYPE_LABEL = {"high": "High School", "middle": "Middle School", "elementary": "Elementary", "other": "Preschool"}


def _parse_date_text(text: str) -> datetime | None:
    # Confirmed real: one cell reads "June 17, 2027*available at 4:00 p.m."
    # - a footnote marker followed by trailing text, not just a bare
    # trailing asterisk - drop everything from the first "*" onward.
    text = text.split("*")[0].strip()
    # Confirmed real: the preschool table's dates are weekday-prefixed
    # ("Monday, November 30, 2026") while every other table's aren't
    # ("October 14, 2026") - try both.
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%A, %B %d, %Y", "%a, %b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=_ET)
        except ValueError:
            continue
    return None


def parse_marking_period_page(html: str) -> list[dict]:
    """Returns a list of {school_type, title, start_date, external_uid}."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find(id="fsPageContent") or soup

    results: list[dict] = []
    current_school_type: str | None = None
    for el in main.descendants:
        if getattr(el, "name", None) == "p":
            # Confirmed real: the "PRESCHOOL REPORT CARD SCHEDULE" heading
            # uses a non-breaking space between the first two words, which
            # silently fails an exact dict-key match otherwise.
            text = " ".join(el.get_text(strip=True).split())
            if text in _HEADING_TO_SCHOOL_TYPE:
                current_school_type = _HEADING_TO_SCHOOL_TYPE[text]
            continue

        if getattr(el, "name", None) != "table":
            continue
        if not current_school_type:
            record_parse_issue("marking_period.scan", "no_matches", selector="table heading")
            continue

        rows = el.find_all("tr")
        if not rows:
            continue
        headers = [td.get_text(strip=True) for td in rows[0].find_all("td")]
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            for header, cell_text in zip(headers, cells):
                start_date = _parse_date_text(cell_text)
                if not start_date:
                    continue
                label = _SCHOOL_TYPE_LABEL.get(current_school_type, current_school_type)
                results.append(
                    {
                        "school_type": current_school_type,
                        "title": f"{label}: {header}",
                        "start_date": start_date,
                        "external_uid": f"marking_period:{current_school_type}:{header}:{start_date.date().isoformat()}",
                    }
                )
        # Each school type's table is consumed once - clear so a later
        # table without its own heading (shouldn't happen, but be safe)
        # doesn't get double-attributed to this same type.
        current_school_type = None

    return results


async def fetch_marking_period_page(url: str) -> list[dict]:
    result = await scraper_client.fetch_html(url, wait_for_selector="table")
    return parse_marking_period_page(result["html"])
