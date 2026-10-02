"""District transportation department info - the "my kid's bus" questions
a parent actually has: who do I call when the bus is late, how do I find
out about delays, what's the late bus after activities, how do I change a
bus stop for one day, and who has the thing my kid left on the bus.

Confirmed real source (Cherry Hill Public Schools, 2026-09-09): the
district's own /departments/transportation page tree on chclc.org
(Finalsite). It's all static policy + contact pages - there is NO
published realtime delay feed anywhere on it; individual route delays of
20+ minutes go out as automated messages to the contact info parents keep
in Genesis, per the department's own "Automated Messages" page. That's
why this is a regular 12h public-source scan, not a fast poll: nothing
on these pages changes minute to minute.

Pages and what's parsed from each (deterministic, no LLM - every one has
a clean, stable shape):
  /departments/transportation            office hours (an <h2>), one <p>
                                          per staff member "Name - Title
                                          email", a closing <p> with the
                                          office address + "Phone: ...
                                          Fax: ..."
  .../late-bus-information               policy <li>s, then per contractor a
                                          <p><strong>Name (phone)</strong>
                                          followed by <li>SCHOOL ... Routes:
                                          X, Y</li> lines
  .../automated-messages                 one <p>: the delay-notification policy
  .../bus-guidelines                     the <li> containing the same-day bus
                                          stop change procedure ("11:30am")
  .../bus-stop-change-request/change-request-guidelines-and-form
                                          the "October 31st" deadline <p> and
                                          the request-form link
  .../lost-items                         the "3 days" driver-holds-items <p>
"""

import asyncio
import html as html_lib
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

import scraper_client

_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_ROUTES_RE = re.compile(r"^\s*([A-Z][A-Za-z.' ]+?)\s+(?:Middle|High|Elementary)?\s*School\s+Routes?\s*:\s*(.+)$", re.I)


def _content(html: str) -> BeautifulSoup:
    """Finalsite wraps each page's own content in <main id="fsPageContent">;
    everything outside it is shared chrome (nav, the footer's mission
    statement + copyright). Every parser works inside that container -
    a real bug otherwise: the live delay-policy text came back with
    "Our Mission Statement: ... © Copyright 2024" appended, because the
    saved fixtures had been pre-scoped but the live fetch wasn't."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find(id="fsPageContent")
    return BeautifulSoup(str(main), "lxml") if main else soup


def _text(el) -> str:
    # The pages mix in non-breaking (\xa0) and narrow no-break (\u202f)
    # spaces - normalize so names/titles don't carry them into the DB.
    return el.get_text(" ", strip=True).replace("\xa0", " ").replace("\u202f", " ").strip() if el else ""


def parse_main(html: str) -> dict:
    """Office hours, staff contacts, address, phone, fax."""
    soup = _content(html)
    result: dict = {"office_hours": None, "contacts": [], "office_address": None, "office_phone": None, "office_fax": None}

    for h in soup.find_all(["h2", "h3"]):
        t = _text(h)
        if re.search(r"office hours", t, re.I):
            m = re.search(r"office hours (?:are|:)?\s*(.+?)\.?$", t, re.I)
            result["office_hours"] = (m.group(1) if m else t).strip()
            break

    for p in soup.find_all("p"):
        t = _text(p)
        email = _EMAIL_RE.search(t)
        if email and " - " in t.replace("-", " - ", 1) and "Phone" not in t:
            # "Mr. Jason Schimpf- Assistant Superintendent/... jschimpf@chclc.org"
            before_email = t[: email.start()].strip()
            name, _, title = before_email.partition("-")
            if not title:
                name, _, title = before_email.partition("–")
            result["contacts"].append({"name": name.strip(" -–"), "title": title.strip(" -–"), "email": email.group(0)})
            continue
        if "Phone" in t and _PHONE_RE.search(t):
            phones = _PHONE_RE.findall(t)
            phone_m = re.search(r"Phone:\s*(" + _PHONE_RE.pattern + ")", t)
            fax_m = re.search(r"Fax:\s*(" + _PHONE_RE.pattern + ")", t)
            result["office_phone"] = phone_m.group(1) if phone_m else (phones[0] if phones else None)
            result["office_fax"] = fax_m.group(1) if fax_m else None
            # Address is everything between the office name and "Phone:".
            addr = re.sub(r"^\s*District Transportation Office\s*", "", t)
            addr = addr.split("Phone:")[0]
            addr = re.sub(r"\s*[·ꞏ•]\s*", ", ", addr).strip(" ,")
            result["office_address"] = addr or None
    return result


def parse_late_bus(html: str) -> dict:
    """Policy bullets + contractors with their per-school route lists."""
    soup = _content(html)
    policy: list[str] = []
    contractors: list[dict] = []
    current: dict | None = None
    for el in soup.find_all(["p", "li"]):
        t = _text(el)
        if not t:
            continue
        routes_m = _ROUTES_RE.match(t)
        if routes_m and current is not None:
            school_key = routes_m.group(1).strip().upper()
            routes = [r.strip() for r in routes_m.group(2).split(",") if r.strip()]
            current["routes"][school_key] = routes
            continue
        phone_m = _PHONE_RE.search(t)
        if el.name == "p" and phone_m and el.find("strong") is not None and "Contractors" not in t:
            # "First Student - Berlin (856) 753-0222"
            name = t[: phone_m.start()].strip(" -(")
            current = {"name": name, "phone": phone_m.group(0), "routes": {}}
            contractors.append(current)
            continue
        if el.name == "li" and current is None:
            policy.append(t)
    return {"late_bus_policy": " ".join(policy) or None, "late_bus_contractors": contractors}


def parse_delay_policy(html: str) -> str | None:
    soup = _content(html)
    paras = [_text(p) for p in soup.find_all("p") if _text(p)]
    return " ".join(paras) or None


def parse_bus_stop_change(guidelines_html: str, change_request_html: str, base_url: str) -> dict:
    result: dict = {"bus_stop_change_procedure": None, "bus_stop_change_deadline": None, "bus_stop_change_form_url": None}
    g = _content(guidelines_html)
    for el in g.find_all(["li", "p"]):
        t = _text(el)
        if "11:30" in t and re.search(r"change", t, re.I):
            result["bus_stop_change_procedure"] = t
            break
    c = _content(change_request_html)
    for p in c.find_all("p"):
        t = _text(p)
        if re.search(r"accepted until", t, re.I):
            result["bus_stop_change_deadline"] = t
            break
    for a in c.find_all("a", href=True):
        if re.search(r"request form", _text(a), re.I):
            href = a["href"]
            result["bus_stop_change_form_url"] = base_url.rstrip("/") + href if href.startswith("/") else href
            break
    return result


def parse_lost_items(html: str) -> str | None:
    soup = _content(html)
    for p in soup.find_all("p"):
        t = _text(p)
        if re.search(r"\b\d+ days\b", t) and re.search(r"driver", t, re.I):
            return t
    return None


_SUBPAGES = {
    "late_bus": "late-bus-information",
    "automated": "automated-messages",
    "guidelines": "bus-guidelines",
    "change_request": "bus-stop-change-request/change-request-guidelines-and-form",
    "lost_items": "lost-items",
    "closing_info": "school-closing-information",
}


async def _fetch_page(url: str, attempts: int = 3, backoff_s: float = 2.0) -> str:
    """One page, with retries. The single scraper instance intermittently
    answers 502 (confirmed real - the same transient failure hit the
    preschool logo scans), and this job needs six pages in a row, so
    failing the whole run on one blip would make it fail most runs."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return (await scraper_client.fetch_html(url, wait_for_selector="#fsPageContent", block_assets=True))["html"]

        except Exception as exc:  # httpx.HTTPStatusError / timeouts
            last = exc
            if attempt < attempts - 1:
                await asyncio.sleep(backoff_s * (attempt + 1))
    assert last is not None
    raise last


def _decode_cfemail(hexed: str) -> str | None:
    try:
        raw = bytes.fromhex(hexed)
        return "".join(chr(b ^ raw[0]) for b in raw[1:])
    except (ValueError, IndexError):
        return None


_ESV_CONTACT_RE = re.compile(r"^(?:(?:Mr|Mrs|Ms|Dr)\.?\s+)?(.+?)\s+[-\u2013]\s+(.*Transportation.*)$")
_ESV_HEADING_RE = re.compile(r"^[A-Z][A-Z &/,'\-]{5,}$")


def parse_eschoolview_page(html: str, page_url: str) -> dict:
    """eSchoolView/LINQ (Mount Laurel): one server-rendered page holds the
    whole department - office block ("354 Mount Laurel Road . Mount Laurel, NJ"
    then "Phone: ... . Fax: ..."), hours, staff as "Name - Title" followed by
    a Cloudflare-obfuscated email (`data-cfemail`, decoded here), then policy
    sections under all-caps headings. No late-bus contractor table exists, so
    that stays empty. Everything is scoped from the "District Transportation
    Office" line on, because the page's mega-menu repeats before it."""
    soup = BeautifulSoup(html, "lxml")
    for el in soup.select("[data-cfemail]"):
        el.replace_with(" " + (_decode_cfemail(el["data-cfemail"]) or "") + " ")
    lines = [re.sub(r"\s+", " ", html_lib.unescape(l)).strip() for l in soup.get_text("\n").split("\n")]
    lines = [l for l in lines if l]
    start = next((i for i, l in enumerate(lines) if l.lower() == "district transportation office"), None)
    result: dict = {
        "office_phone": None, "office_fax": None, "office_hours": None, "office_address": None, "contacts": [],
        "delay_policy": None, "late_bus_policy": None, "late_bus_contractors": [], "bus_stop_change_procedure": None,
        "bus_stop_change_deadline": None, "bus_stop_change_form_url": None, "lost_items_policy": None,
        "main_url": page_url, "late_bus_url": page_url, "guidelines_url": page_url, "lost_items_url": page_url, "closing_info_url": None,
    }
    if start is None:
        return result
    body = lines[start:]

    for i, l in enumerate(body[:6]):
        if "Phone:" in l:
            phone = re.search(r"Phone:\s*(" + _PHONE_RE.pattern + ")", l)
            fax = re.search(r"Fax:\s*(" + _PHONE_RE.pattern + ")", l)
            result["office_phone"] = phone.group(1) if phone else None
            result["office_fax"] = fax.group(1) if fax else None
            if i > 1:
                result["office_address"] = re.sub(r"\s*[\u00b7\u2022]\s*", ", ", body[i - 1]).strip(" ,")
            break

    sections: dict[str, list[str]] = {}
    current = None
    for l in body[1:]:
        if _ESV_HEADING_RE.match(l):
            current = l
            sections[current] = []
        elif current is not None:
            sections[current].append(l)
        else:
            hours = re.search(r"office hours (?:are|:)?\s*(.+?)\.?$", l, re.I)
            if hours:
                result["office_hours"] = hours.group(1)
            m = _ESV_CONTACT_RE.match(l)
            if m:
                result["contacts"].append({"name": m.group(1).strip(), "title": m.group(2).strip(), "email": None})
            elif result["contacts"] and result["contacts"][-1]["email"] is None and _EMAIL_RE.fullmatch(l):
                result["contacts"][-1]["email"] = l

    def section(prefix: str) -> str | None:
        for key, vals in sections.items():
            if key.startswith(prefix):
                return " ".join(vals).replace(" .", ".").replace(" ,", ",") or None
        return None

    result["delay_policy"] = section("AUTOMATED TEXT")
    result["late_bus_policy"] = section("LATE & CLUB")
    stop = section("CHANGE OF BUS STOP")
    result["bus_stop_change_procedure"] = stop
    for sentence in re.split(r"(?<=[.!?])\s+", " ".join(sum(sections.values(), []))):
        if re.search(r"\b\d+ days\b", sentence) and re.search(r"driver", sentence, re.I):
            result["lost_items_policy"] = sentence.replace(" ,", ",")
            break
    return result


_EDLIO_EXT_RE = re.compile(r"^ext\.?\s*\d+", re.I)


def _edlio_lines(html: str) -> list[str]:
    main = BeautifulSoup(html, "lxml").find(id="content_main")
    text = main.get_text("\n") if main else ""
    return [l for l in (re.sub(r"\s+", " ", html_lib.unescape(l)).strip() for l in text.split("\n")) if l]


def parse_edlio_transportation(info_html: str, staff_html: str, guidelines_html: str, page_urls: dict[str, str]) -> dict:
    """Edlio (Medford): three small pages under one Transportation department.
    Info prose carries the phone and hours; the staff page is name / title /
    "ext. N" line triples (no email - those are contact forms); the guidelines
    page's "Alternate Bus Stop Location" section is the stop-change rule, with
    its form linked as a PDF. No delay or late-bus pages exist on the site."""
    result: dict = {
        "office_phone": None, "office_fax": None, "office_hours": None, "office_address": None, "contacts": [],
        "delay_policy": None, "late_bus_policy": None, "late_bus_contractors": [], "bus_stop_change_procedure": None,
        "bus_stop_change_deadline": None, "bus_stop_change_form_url": None, "lost_items_policy": None,
        "main_url": page_urls.get("main"), "late_bus_url": None, "guidelines_url": page_urls.get("guidelines"),
        "lost_items_url": None, "closing_info_url": None,
    }
    info = " ".join(_edlio_lines(info_html))
    phone = re.search(r"(" + _PHONE_RE.pattern + r")\s*(?:ext\.?\s*(\d+))?", info[info.lower().find("transportation office"):] if "transportation office" in info.lower() else info, re.I)
    if phone:
        result["office_phone"] = phone.group(1) + (f" ext. {phone.group(2)}" if phone.group(2) else "")
    hours = re.search(r"hours of operation (?:are|is)\s+(.+?)\.", info, re.I)
    if hours:
        result["office_hours"] = hours.group(1)

    lines = _edlio_lines(staff_html)
    start = next((i for i, l in enumerate(lines) if l.lower() == "staff" and i + 1 < len(lines) and lines[i + 1].lower() == "staff"), None)
    body = lines[start + 2:] if start is not None else []
    people: list[dict] = []
    for l in body:
        if l.lower() in {"staff", "transportation information", "guidelines"}:
            break
        if _EDLIO_EXT_RE.match(l):
            if people:
                people[-1]["ext"] = l
        elif people and people[-1]["title"] is None and people[-1].get("ext") is None:
            people[-1]["title"] = l
        else:
            people.append({"name": l, "title": None})
    result["contacts"] = [{"name": p["name"], "title": " - ".join(filter(None, [p["title"], p.get("ext")])) or None, "email": None} for p in people]

    soup = BeautifulSoup(guidelines_html, "lxml")
    main = soup.find(id="content_main") or soup
    procedure = ""
    for block in main.select(".collapsible-block"):
        header = block.select_one(".collapsible-header")
        content = block.select_one(".collapsible-content")
        if header and content and header.get_text(" ", strip=True).lower().startswith("alternate bus stop"):
            procedure = re.sub(r"\s+", " ", content.get_text(" ", strip=True))
            break
    else:
        for heading in main.find_all(["h2", "h3", "h4"]):
            if heading.get_text(" ", strip=True).lower().startswith("alternate bus stop"):
                parts = []
                for sib in heading.find_next_siblings():
                    if sib.name in {"h2", "h3", "h4"}:
                        break
                    parts.append(re.sub(r"\s+", " ", sib.get_text(" ", strip=True)))
                procedure = " ".join(p for p in parts if p)
                break
    if procedure:
        result["bus_stop_change_procedure"] = procedure
        deadline = re.search(r"\bby (?:the )?([^.]*?(?:week of \w+|\w+ \d{1,2}))", procedure)
        result["bus_stop_change_deadline"] = deadline.group(1) if deadline else None
    for a in main.find_all("a", href=True):
        if re.search(r"alternat", a.get_text(" ", strip=True), re.I) and re.search(r"\.pdf|files\.edl\.io", a["href"], re.I):
            result["bus_stop_change_form_url"] = urljoin(page_urls.get("guidelines") or "", a["href"])
            break
    return result


async def _fetch_edlio_page(url: str) -> str:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


async def _discover_edlio_transportation(main_url: str) -> dict:
    """`transportation_url` is any page of the department; the Staff and
    Guidelines pages are found from its left-hand menu by link text."""
    info_html = await _fetch_edlio_page(main_url)
    menu = {a.get_text(" ", strip=True).lower(): urljoin(main_url, a["href"]) for a in BeautifulSoup(info_html, "lxml").find_all("a", href=True)}
    staff_url, guidelines_url = menu.get("staff"), menu.get("guidelines")
    staff_html = await _fetch_edlio_page(staff_url) if staff_url else ""
    guidelines_html = await _fetch_edlio_page(guidelines_url) if guidelines_url else ""
    return parse_edlio_transportation(info_html, staff_html, guidelines_html, {"main": menu.get("transportation information", main_url), "guidelines": guidelines_url or main_url})


async def discover_transportation(transportation_url: str, base_url: str) -> dict:
    """Fetches the department page tree and returns every parsed field
    plus the page URLs themselves (for "read the full policy" links)."""
    main_url = transportation_url.rstrip("/")
    if main_url.lower().endswith(".aspx"):
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as client:
            resp = await client.get(main_url)
            resp.raise_for_status()
        return parse_eschoolview_page(resp.text, main_url)
    if "/apps/pages/" in main_url:
        return await _discover_edlio_transportation(main_url)
    pages: dict[str, str] = {}
    pages["main"] = await _fetch_page(main_url)
    for key, slug in _SUBPAGES.items():
        if key == "closing_info":
            continue  # just a link-out, nothing to parse
        pages[key] = await _fetch_page(f"{main_url}/{slug}")

    result = {
        **parse_main(pages["main"]),
        **parse_late_bus(pages["late_bus"]),
        "delay_policy": parse_delay_policy(pages["automated"]),
        **parse_bus_stop_change(pages["guidelines"], pages["change_request"], base_url),
        "lost_items_policy": parse_lost_items(pages["lost_items"]),
        "main_url": main_url,
        "late_bus_url": f"{main_url}/{_SUBPAGES['late_bus']}",
        "guidelines_url": f"{main_url}/{_SUBPAGES['guidelines']}",
        "lost_items_url": f"{main_url}/{_SUBPAGES['lost_items']}",
        "closing_info_url": f"{main_url}/{_SUBPAGES['closing_info']}",
    }
    return result


def late_bus_for_school(contractors: list[dict] | None, school_name: str, short_name: str | None) -> dict | None:
    """Resolves which late-bus contractor (if any) serves a school by
    matching the page's all-caps school key ("BECK", "EAST", "CARUSI")
    against the school's own name. Elementary schools have no late bus at
    all (confirmed: only the three middle and two high schools are
    listed), so this returns None for them."""
    if not contractors:
        return None
    haystack = f"{school_name} {short_name or ''}".upper()
    for c in contractors:
        for key, routes in (c.get("routes") or {}).items():
            if re.search(r"\b" + re.escape(key) + r"\b", haystack):
                return {"contractor": c["name"], "phone": c["phone"], "routes": routes}
    return None
