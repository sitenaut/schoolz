"""Parses the district's own "Preschool Locations" page - a public
directory of preschool providers that host the district's contracted PreK
seats. Confirmed real (Cherry Hill Public Schools): most of these are
private third-party businesses on their own websites (Adventure Kids,
Cadence Academy, Chesterbrook Academy, Discovery Corner, Goddard School,
Kindercare, Lightbridge Academy, Mosaic Early Learning Center, Primrose
School) - none of them are Finalsite sites, so the existing school_info/
staff_roster/documents scans (built around Finalsite's specific DOM
structure) don't apply and aren't run for them. Two of the listed
locations (Joyce Kilmer Preschool, Estelle V. Malberg Early Childhood
Center) are the SAME physical building as an already-tracked School - not
new entities, so this parser is matched against existing addresses to
avoid creating duplicates for those two.

Deterministic HTML parsing (like marking_period.py), not an LLM pass - the
page's structure is consistent enough per-listing: a name link (often
wrapping a real external website URL), address lines, a "Ph. ..." phone
line, and a "Email X, <title>" contact line, each separated by <br>.
"""

import re

from bs4 import BeautifulSoup

_PHONE_RE = re.compile(r"Ph\.?:?\s*([\(\d][\d\s\-\(\)\.]{7,}\d)")
_SKIP_LINE_PREFIXES = ("ph.", "ph:", "email", "directions", "fax")


def _parse_block(container) -> dict | None:
    # The name is always the first <strong> in the block - usually wrapped
    # in a link to the provider's own site, but not always (confirmed real:
    # "Joyce Kilmer Preschool" has no site link, just plain bold text).
    name_tag = container.find("strong")
    if not name_tag:
        return None

    name = name_tag.get_text(strip=True)
    website_url = name_tag.parent.get("href") if name_tag.parent.name == "a" else None
    full_text = container.get_text("\n", strip=True)

    address_lines = []
    for line in full_text.split("\n"):
        line = line.strip()
        if not line or line == name:
            continue
        if line.lower().startswith(_SKIP_LINE_PREFIXES):
            break
        address_lines.append(line)
    address = ", ".join(address_lines) if address_lines else None

    phone_match = _PHONE_RE.search(full_text)
    main_phone = phone_match.group(1).strip() if phone_match else None

    email_anchor = container.find("a", href=lambda h: bool(h) and h.startswith("mailto:"))
    contact_email = email_anchor["href"].replace("mailto:", "").strip() if email_anchor else None

    return {
        "name": name,
        "website_url": website_url,
        "address": address,
        "main_phone": main_phone,
        "contact_email": contact_email,
    }


def parse_preschool_locations(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find(id="fsPageContent") or soup

    results = []
    seen_names: set[str] = set()
    for container in main.find_all(["p", "td"]):
        entry = _parse_block(container)
        if not entry or entry["name"] in seen_names:
            continue
        seen_names.add(entry["name"])
        results.append(entry)
    return results
