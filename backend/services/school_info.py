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

import json
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

import scraper_client
from services import smart_sites

_PLAIN_PHONE_RE = re.compile(r"\(?\d{3}\)?[-. ]?\d{3}[-. ]\d{4}")

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


def _img_url(img) -> str | None:
    """The URL an <img> will actually show. Finalsite server-renders its
    header logo as `<img src="" data-image-sizes='[{"url": ..., "width": N}]'>`
    and fills `src` with JavaScript, so a page fetched without that script
    finishing has an empty src; urljoin(base, "") is the page itself, which
    once got stored as the school's logo and rendered as a broken image."""
    src = (img.get("src") or "").strip()
    if src and not src.startswith("data:"):
        return src
    if (lazy := (img.get("data-src") or "").strip()) and not lazy.startswith("data:"):
        return lazy
    try:
        sizes = json.loads(img.get("data-image-sizes") or "[]")
    except ValueError:
        return None
    candidates = [x for x in sizes if isinstance(x, dict) and x.get("url")] if isinstance(sizes, list) else []
    return max(candidates, key=lambda x: x.get("width") or 0)["url"] if candidates else None


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
    # (img, effective url): an <img> with no real URL anywhere is skipped,
    # never turned into the page's own URL by urljoin(base, "").
    images = [(img, url) for img in header.find_all("img") if (url := _img_url(img)) and not any(bad in url.lower() for bad in _LOGO_SRC_EXCLUDE)]
    # Prefer one that actually says "logo" (catches a case like Mosaic's
    # own markup, where the real logo's alt text is "Home" but a
    # shopping-cart icon happens to come first in the header) before
    # falling back to whichever comes first.
    logo_like = next((c for c in images if "logo" in c[1].lower() or "logo" in (c[0].get("alt") or "").lower()), None)
    chosen = logo_like or (images[0] if images else None)
    if not chosen:
        return None
    # urljoin (not manual string concatenation) handles both an
    # absolute-path src ("/content/dam/...") and a page-relative one
    # correctly - a real bug otherwise: a school website_url that
    # includes its own path (e.g. goddardschool.com/schools/nj/...,
    # unlike the Finalsite sites' bare-domain URLs) turned an
    # absolute-path src into a broken concatenated URL.
    return urljoin(base_url + "/", chosen[1])


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
    else:
        # Some Finalsite footers (Merchantville) print "P: (856) 663-1091" as
        # plain text with no tel: link.
        phone_box = soup.select_one(".fsLocationPhone")
        match = _PLAIN_PHONE_RE.search(phone_box.get_text(" ", strip=True)) if phone_box else None
        if match:
            result["main_phone"] = match.group(0)

    return result


_ESV_ADDRESS_RE = re.compile(r"^(.+?)\s*\n\s*([^\n]+,\s*NJ\s+\d{5})\s*\n\s*Phone:\s*([^\n]+)", re.M)


def _parse_eschoolview_footer(html: str, page_url: str) -> dict | None:
    """eSchoolView/LINQ (Mount Laurel): no `fsLocation*` widget - the menu
    ends with three plain lines, street / "City, NJ zip" / "Phone: ...". None
    when the page doesn't have them, so any other platform falls through."""
    soup = BeautifulSoup(html, "lxml")
    match = _ESV_ADDRESS_RE.search("\n".join(soup.get_text("\n", strip=True).split("\n")))
    if not match:
        return None
    phone = _PLAIN_PHONE_RE.search(match.group(3))
    return {
        "address": f"{match.group(1).strip()}, {match.group(2).strip()}",
        "main_phone": phone.group(0) if phone else None,
        # The header's src is page-relative ("sysimages/Logos/X.png"), so join
        # against the page's directory, not the page itself.
        "logo_url": _find_logo_url(html, page_url.rsplit("/", 1)[0]),
    }


def _parse_edlio_footer(html: str, base_url: str) -> dict | None:
    """Edlio (Medford): the footer's "Contact Us" block holds the address as a
    link to `/apps/maps` and the phone as a `tel:` link. None for any other
    platform (no such link), so the Finalsite path still runs."""
    soup = BeautifulSoup(html, "lxml")
    address = None
    maps = soup.select_one(".footer-info-block a[href$='/apps/maps']")
    if maps:
        phone = soup.select_one(".footer-info-block a[href^='tel:']")
        phone_text = phone.get_text(strip=True) if phone else None
    else:
        # Stratford's Edlio sites use `.enf-address`: the phone is plain
        # "P: (856) ..." text inside a `/apps/contact` link, not a tel: link.
        maps = soup.select_one(".enf-address a[href$='/apps/maps']")
        if not maps:
            return None
        address = ", ".join(maps.stripped_strings)
        contact = soup.select_one(".enf-address a[href$='/apps/contact']")
        match = _PLAIN_PHONE_RE.search(contact.get_text(" ", strip=True)) if contact else None
        phone_text = match.group(0) if match else None
    return {
        "address": address if address else re.sub(r"\s+", " ", maps.get_text(" ", strip=True)),
        "main_phone": phone_text,
        "logo_url": _find_logo_url(html, base_url),
    }


_PRESENCE_PHONE_RE = re.compile(r"Phone[:\s]{0,20}(\(?\d{3}\)?[-. ]?\d{3}[-. ]\d{4})")


def _parse_presence_footer(html: str, base_url: str) -> dict | None:
    """SchoolMessenger Presence (ex-SharpSchool; Sterling, Somerdale): the
    footer's address is a text node in `.address` or `#footer-address`, the
    phone a "Phone 856-..." run beside it (Somerdale nests it inside the
    address box). Sterling spells the state out ("New Jersey"). None for any
    other platform."""
    soup = BeautifulSoup(html, "lxml")
    box = soup.select_one("#footer .address") or soup.select_one("#footer-address")
    if not box:
        return None
    address = " ".join(" ".join(box.find_all(string=True, recursive=False)).split())
    if not address:
        return None
    address = re.sub(r"\bNew Jersey\b", "NJ", address)
    phone = _PRESENCE_PHONE_RE.search(" ".join((box.parent or box).get_text(" ", strip=True).split()))
    return {
        "address": address,
        "main_phone": phone.group(1) if phone else None,
        "logo_url": _find_logo_url(html, base_url),
    }


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
    smart_home = await smart_sites.fetch_home(base)
    if smart_home:
        return {**smart_sites.parse_footer(smart_home), "logo_url": _find_logo_url(smart_home, base)}
    if base.lower().endswith(".aspx"):
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as client:
                resp = await client.get(base)
            esv = _parse_eschoolview_footer(resp.text, str(resp.url)) if resp.status_code == 200 else None
        except httpx.HTTPError:
            esv = None
        if esv:
            return esv
    if not base.lower().endswith(".aspx"):
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as client:
                resp = await client.get(base + "/")
            edlio = (_parse_edlio_footer(resp.text, base) or _parse_presence_footer(resp.text, base)) if resp.status_code == 200 else None
        except httpx.HTTPError:
            edlio = None
        if edlio:
            return edlio
    try:
        # Confirmed real: plain "footer" resolves to 2 elements on these
        # pages (one hidden), so Playwright's visibility wait times out -
        # the actual widget class is unambiguous.
        result = await scraper_client.fetch_html(base + "/", wait_for_selector=".fsLocationAddress")
    except Exception:
        result = await scraper_client.fetch_html(base + "/")
    return _parse_location(result["html"], base)
