"""Discovers a school's public directory info (address, main phone) from
its own Finalsite site. Confirmed real structure (Cherry Hill Public
Schools, consistent across every school checked): every page's footer
carries a standard `fsLocationSingleItem` widget -

    <div class="fsLocationAddress ...">140 Old Carriage Road</div>
    <div class="fsAddressWrap">
        <div class="fsLocationCity">Cherry Hill</div>
        <div class="fsLocationState">NJ</div>
        <div class="fsLocationZip">08034</div>
    </div>
    <div class="fsLocationPhone"><a href="tel:...">(856) 428-0830</a></div>

- so a single homepage fetch is enough; no need to visit a dedicated
contact page. `website_url` itself isn't discovered here (there's no way
to find a school's site without already knowing it, and every tracked
school already has one) - this just verifies it resolves."""

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import scraper_client

# Finalsite pages embed a Google Translate widget badge inside <header>
# ahead of the real school logo on some sites (confirmed: Bret Harte,
# Beck); the district's private-preschool sites (not Finalsite) embed
# their own social-icon/cart-icon clutter in <header> the same way
# (confirmed: Discovery Corner's Facebook/Instagram icons, Mosaic's
# shopping-cart icon on its Drupal commerce theme, a gtranslate flag SVG).
# None of these are ever the school's own logo.
_LOGO_SRC_EXCLUDE = ("gstatic.com", "fb-icon", "ig-icon", "facebook", "instagram", "/flags/", "cart.png", "icon-home")

# Two real, confirmed exceptions where the generic "first header image"
# heuristic finds a technically-real logo that's useless in the app (a
# white-on-transparent mark that's invisible against the app's light
# card background) - checked 2026-09-09 by rendering each candidate on a
# white background. Falls back to that school's own favicon (Primrose) or
# apple-touch-icon (KinderCare), which are colored and legible instead.
# Mosaic (centerffs.org) has no usable alternative found - explicitly
# `None` so the generic heuristic's pale, low-contrast pick is skipped
# rather than silently used; the school just shows its color dot instead.
_KNOWN_LOGO_OVERRIDES: dict[str, str | None] = {
    "www.primroseschools.com": "https://www.primroseschools.com/favicon.ico",
    "www.kindercare.com": "https://www.kindercare.com/-/media/kindercare/favicons/apple-icon.png",
    "www.centerffs.org": None,
}


def _find_logo_url(html: str, base_url: str) -> str | None:
    """First image inside <header> that isn't a known widget/icon badge -
    confirmed real across 4 Cherry Hill Finalsite schools (elementary,
    middle, both high schools) and 7 of the district's private preschool
    sites checked (Adventure Kids, Cadence, Chesterbrook, Discovery
    Corner, Lightbridge, Goddard's compact brand-mark): the school's own
    logo is the first substantive <img> in the page header regardless of
    what site software runs it, once known widget noise is excluded."""
    domain = urlparse(base_url).netloc
    if domain in _KNOWN_LOGO_OVERRIDES:
        return _KNOWN_LOGO_OVERRIDES[domain]

    soup = BeautifulSoup(html, "lxml")
    header = soup.find("header") or soup
    images = [img for img in header.find_all("img", src=True) if not any(bad in img["src"].lower() for bad in _LOGO_SRC_EXCLUDE)]
    # Prefer one that actually says "logo" (catches a case like Mosaic's
    # own markup, where the real logo's alt text is "Home" but a
    # shopping-cart icon happens to come first in the header) before
    # falling back to whichever comes first.
    logo_like = next((img for img in images if "logo" in img["src"].lower() or "logo" in (img.get("alt") or "").lower()), None)
    chosen = logo_like or (images[0] if images else None)
    if not chosen:
        return None
    # urljoin (not manual string concatenation) handles both an
    # absolute-path src ("/content/dam/...") and a page-relative one
    # correctly - a real bug otherwise: a school website_url that
    # includes its own path (e.g. goddardschool.com/schools/nj/...,
    # unlike the Finalsite sites' bare-domain URLs) turned an
    # absolute-path src into a broken concatenated URL.
    return urljoin(base_url + "/", chosen["src"])


def _parse_location(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    result: dict = {"address": None, "main_phone": None, "logo_url": _find_logo_url(html, base_url)}

    street = soup.select_one(".fsLocationAddress")
    city = soup.select_one(".fsLocationCity")
    state = soup.select_one(".fsLocationState")
    zip_code = soup.select_one(".fsLocationZip")
    if street:
        parts = [street.get_text(strip=True)]
        city_state_zip = ", ".join(filter(None, [city.get_text(strip=True) if city else None, state.get_text(strip=True) if state else None]))
        if zip_code:
            city_state_zip = f"{city_state_zip} {zip_code.get_text(strip=True)}".strip()
        if city_state_zip:
            parts.append(city_state_zip)
        result["address"] = ", ".join(parts)

    phone_link = soup.select_one(".fsLocationPhone a[href^='tel:']")
    if phone_link:
        result["main_phone"] = phone_link.get_text(strip=True)

    return result


async def discover_school_info(school_website_url: str) -> dict:
    """Returns {"address": str|None, "main_phone": str|None, "logo_url": str|None}.

    The address/phone widget is Finalsite-specific - most tracked schools
    run Finalsite, but the district's private preschools (Adventure Kids,
    Cadence, Chesterbrook, etc.) each run their own unrelated site
    software, so waiting on `.fsLocationAddress` there would just time
    out. Falls back to a plain fetch (no selector wait) so logo discovery
    - which doesn't depend on Finalsite markup - still works on those;
    address/phone simply come back null for them (already handled as a
    normal "nothing found" case by the caller, since those schools'
    address/phone come from `preschool_locations.scan` instead)."""
    base = school_website_url.rstrip("/")
    try:
        # Confirmed real: plain "footer" resolves to 2 elements on these
        # pages (one hidden), so Playwright's visibility wait times out -
        # the actual widget class is unambiguous.
        result = await scraper_client.fetch_html(base + "/", wait_for_selector=".fsLocationAddress")
    except Exception:
        result = await scraper_client.fetch_html(base + "/")
    return _parse_location(result["html"], base)
