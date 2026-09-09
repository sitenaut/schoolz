"""Fetches and parses a school's own staff directory (Finalsite
`/contact-us`, confirmed structure: `.fsConstituentItem` cards, paginated
via `?const_page=N`, with a stable `data-constituent-id` per person that
survives re-scans even if name formatting changes slightly)."""

from bs4 import BeautifulSoup

import scraper_client


def _text_after_label(el, label: str) -> str | None:
    text = el.get_text(" ", strip=True)
    text = text.replace(label, "", 1).strip()
    return text or None


_NEXT_PAGE_SELECTOR = "a.fsNextPageLink"


def _parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    for el in soup.select(".fsConstituentItem"):
        constituent_id = el.get("data-constituent-id")
        name_el = el.select_one(".fsFullName")
        name = name_el.get_text(strip=True) if name_el else None
        if not constituent_id or not name:
            continue

        title_el = el.select_one(".fsTitles")
        department_el = el.select_one(".fsDepartments")
        email_el = el.select_one(".fsEmail a[href^='mailto:']")
        phone_el = el.select_one(".fsPhones a[href^='tel:']")

        items.append(
            {
                "constituent_id": constituent_id,
                "full_name": name,
                "title": _text_after_label(title_el, "Titles:") if title_el else None,
                "department": _text_after_label(department_el, "Departments:") if department_el else None,
                "email": email_el["href"].replace("mailto:", "").strip() if email_el else None,
                "phone": phone_el.get_text(strip=True) if phone_el else None,
            }
        )
    return items


_DIRECTORY_PATHS = ("/contact-us", "/contact-us/alphabetical-staff-directory")


async def fetch_roster(school_website_url: str) -> list[dict]:
    """Paginates by actually clicking the "next page" control in one live
    browser session - confirmed the directory's ?const_page=N query param
    does nothing on its own (client-side/JS pagination, not real
    server-side paging), so a plain per-page fetch just returns page 1
    every time.

    Most schools' directory lives directly at /contact-us, but some (seen on
    the district's high schools) instead put it at
    /contact-us/alphabetical-staff-directory - try both, in order, and use
    the first one that actually yields results."""
    base = school_website_url.rstrip("/")
    for path in _DIRECTORY_PATHS:
        pages_html = await scraper_client.fetch_paginated(base + path, next_page_selector=_NEXT_PAGE_SELECTOR, max_pages=20)
        by_constituent_id: dict[str, dict] = {}
        for html in pages_html:
            for item in _parse_page(html):
                by_constituent_id[item["constituent_id"]] = item
        if by_constituent_id:
            return list(by_constituent_id.values())

    return []
