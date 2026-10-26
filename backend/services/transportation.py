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
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString

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


async def _discover_edlio_transportation(main_url: str, info_html: str) -> dict:
    """`transportation_url` is any page of the department; the Staff and
    Guidelines pages are found from its left-hand menu by link text."""
    menu = {a.get_text(" ", strip=True).lower(): urljoin(main_url, a["href"]) for a in BeautifulSoup(info_html, "lxml").find_all("a", href=True)}
    staff_url, guidelines_url = menu.get("staff"), menu.get("guidelines")
    staff_html = await _fetch_edlio_page(staff_url) if staff_url else ""
    guidelines_html = await _fetch_edlio_page(guidelines_url) if guidelines_url else ""
    return parse_edlio_transportation(info_html, staff_html, guidelines_html, {"main": menu.get("transportation information", main_url), "guidelines": guidelines_url or main_url})


# A department that is one page, or one page plus a Staff and a Regulations
# page (Waterford on Finalsite; Winslow, Burlington City, Woodbury and
# Camden County Technical on Educational Networks). Their pages share no
# layout, so this reads only what any of them states in a recognisable
# form, and only inside the page's own content container: the Cherry Hill
# parsers read whole pages elsewhere and stored Clayton's and Willingboro's
# footers, and a Google Site's "page does not exist", as bus policies.

# Last, Presence's `.pageContent` (Delran), whose pages have neither of the landmarks before it.
_CONTENT_SELECTORS = ("#fsPageContent", "#pageContentWrapper", "#content_main", "main", "[role=main]", ".pageContent")
_BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "td", "th", "tr", "table", "dt", "dd", "dl", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote"}
# Finalsite's hidden "(opens in new window)" after a link (smore_parser._visible_text).
_SCREEN_READER_ONLY_RE = re.compile(r"sr-?only|visually-hidden", re.I)
# Not inside a longer run of digits: Willingboro's form link (jotform.com/252615042372046) read as a phone.
_PHONE_EXT_RE = re.compile(r"(?<![\w/])" + _PHONE_RE.pattern + r"(?!\d)(?:\s*,?\s*(?:x|ext\.?|extension)\s*#?\d+(?:\s*(?:or|/|,)\s*(?:x|ext\.?)?\s*\d+)*)?", re.I)
# Matched per sentence, so the hours run to its end ("are Monday through Friday from 7:00AM - 4:30PM during the school year.",
# "The Transportation office at Eastern is located in Room 700 and is open from 6:30am to 2:30pm daily.").
_OFFICE_HOURS_RE = re.compile(
    r"\bhours\b(?: of [\w ]+?)?\s+(?:are|is)\s+(.+?)(?<![ap]\.m)\.?$|\btransportation (?:office|department)\b[^.]*?\bis open (?:from )?(.+?)(?<![ap]\.m)\.?$", re.I
)
_ADDRESS_RE = re.compile(r"^\d+ [\w .'-]+, [\w .'-]+,? (?:NJ|New Jersey)\.? \d{5}(?:-\d{4})?$")
_DELAY_RE = re.compile(
    r"outside (?:of )?(?:the )?(?:office|business|regular) hours|after hours|running (?:more than )?\d+ minutes late|delay of (?:more than )?\d+ minutes|delays? of \d+ minutes or more", re.I
)
# A FAQ's question ("The morning bus is late. What should I do?") is answered by the line after it.
# "the late bus" is the after-activities bus, not a late one (Voorhees: "My student took the late bus from VMS...").
_DELAY_QUESTION_RE = re.compile(r"\bbus\b.*\blate\b(?! bus)|\blate\b(?! bus).*\bbus\b|where (?:is )?the bus\b(?! stop)", re.I)
_LOST_QUESTION_RE = re.compile(r"\blost\b|\bleft (?:\w+ )?(?:something|an item|items?)\b", re.I)
_LATE_BUS_RE = re.compile(r"after[- ]school (?:activit|event)|activity bus|late bus|club bus", re.I)
# Who runs the daily buses when it isn't this district: a county vocational
# school's students ride their home district's buses (Camden County
# Technical), and a district whose homes all sit inside the walking limit
# buses only the exceptions (Woodbury).
_OTHER_DISTRICT_BUSES_RE = re.compile(r"provided by (?:the |your )?(?:student[’']?s[’']? |child[’']?s )?(?:sending|home|local|resident) (?:school )?district", re.I)
_DAILY_BUSES_RE = re.compile(_OTHER_DISTRICT_BUSES_RE.pattern + r"|not required to (?:provide )?transport", re.I)
# "If at any time you need assistance, please contact the transportation department at 856-629-6400 EXT. #3" (Monroe).
_CONTACT_SENTENCE_RE = re.compile(r"\b(?:contact|call|reach)\b[^.]*?\btransportation (?:department|office)\b[^.]*?\bat\s*$", re.I)
_STOP_FORM_RE = re.compile(r"\bstop\b.*\b(?:request|change)\b|\b(?:sitter|alternate|change of)\b.*\bstop\b|alternate transportation", re.I)
# The address a district names as the way to reach the office, a person's or not:
# "The best means of contact is via email to transportation@eccrsd.us" (Eastern, Voorhees).
_OFFICE_EMAIL_SENTENCE_RE = re.compile(r"best (?:means|way) (?:of|to) contact\b|\bemail (?:the |our )?transportation (?:department|office|coordinator)\b", re.I)
# Labels that name the kind of number, not whose it is ("Office: ...", "Cell: ...").
_PHONE_KIND_RE = re.compile(r"^(?:phone|telephone|tel\.?|office|main|direct|cell|fax|p|f)\b", re.I)


def _lines(node) -> list[str]:
    """The text as the browser lays it out: one line per block element or
    <br>, inline runs joined as written ("21<sup>st</sup>" stays "21st")."""
    out: list[str] = []
    buf: list[str] = []

    def flush():
        line = re.sub(r"\s+", " ", "".join(buf).replace("​", "").replace("﻿", "")).strip()
        if line:
            out.append(line)
        buf.clear()

    def walk(el):
        for child in el.children:
            if isinstance(child, NavigableString):
                if type(child) is NavigableString:  # not a comment or CDATA
                    buf.append(str(child))
            elif child.name in ("script", "style", "noscript") or _SCREEN_READER_ONLY_RE.search(" ".join(child.get("class") or [])):
                continue
            elif child.name == "br":
                flush()
            elif child.name in _BLOCK_TAGS:
                flush()
                walk(child)
                flush()
            else:
                walk(child)

    walk(node)
    flush()
    return out


def _content_box(html: str):
    soup = BeautifulSoup(html, "lxml")
    return next((el for sel in _CONTENT_SELECTORS if (el := soup.select_one(sel)) is not None), None)


def _sentences(line: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z*(])", line) if s]


def _phone_lines(lines: list[str]) -> dict[int, tuple[re.Match, str]]:
    """Each line that is a phone behind at most a short label ("Telephone:",
    "- Transportation Office"), with its match and that label. A number
    inside a sentence is someone else's (Waterford's after-hours First
    Student line), and so is one in a run of named numbers, which is a list
    of bus companies (Voorhees: "First Student, Berlin Depot 856-751-0222",
    "Hillman's Bus Service 856-751-1123", ...)."""
    found: dict[int, tuple[re.Match, str]] = {}
    for i, line in enumerate(lines):
        m = _PHONE_EXT_RE.search(line)
        if m:
            label = (line[: m.start()] + line[m.end():]).strip(" -–:,.")
            if len(label) <= 45:
                found[i] = (m, label)
    named = {i for i, (_, label) in found.items() if label and not _PHONE_KIND_RE.match(label)}
    listed = {i for i in named if i - 1 in named or i + 1 in named}
    return {i: v for i, v in found.items() if i not in listed}


def _office_phone(lines: list[str]) -> str | None:
    """The department's number: a phone line whose label, or a short line
    up to four above it (a title, a heading, a "Phone" label), is about
    transportation. Failing that, a sentence that says to contact the
    transportation office at a number (Monroe)."""
    for i, (m, label) in _phone_lines(lines).items():
        before = lines[max(0, i - 4) : i]
        if re.search(r"\b(?:fax|cell)\b", label, re.I) or (before and re.fullmatch(r"(?:fax|cell)\W*", before[-1], re.I)):
            continue
        if re.search(r"transport|\bbus", label, re.I) or any(len(b) <= 60 and re.search(r"transport|\bbus", b, re.I) for b in before):
            return m.group(0).strip()
    for line in lines:
        for m in _PHONE_EXT_RE.finditer(line):
            if _CONTACT_SENTENCE_RE.search(line[: m.start()]):
                return m.group(0).strip()
    return None


def _office_fax(lines: list[str]) -> str | None:
    for i, line in enumerate(lines):
        m = _PHONE_EXT_RE.search(line)
        if m and (re.match(r"fax\b", line, re.I) or (i and re.fullmatch(r"fax\W*", lines[i - 1], re.I))):
            return m.group(0).strip()
    return None


def _office_hours(lines: list[str]) -> str | None:
    for i, line in enumerate(lines):
        for sentence in _sentences(line):
            if m := _OFFICE_HOURS_RE.search(sentence):
                return (m.group(1) or m.group(2)).strip()[:200]
        # A "Hours" label over the times (Delran).
        if re.fullmatch(r"(?:office )?hours:?", line, re.I) and i + 1 < len(lines) and re.search(r"\d", lines[i + 1]):
            return lines[i + 1][:200]
    return None


def _office_email(lines: list[str]) -> str | None:
    """The department's mailbox (transportation@...), or the address the
    page names as the way to reach the office. Never a person's address
    just because it appears on the page."""
    for line in lines:
        for sentence in _sentences(line):
            if _OFFICE_EMAIL_SENTENCE_RE.search(sentence) and (m := _EMAIL_RE.search(sentence)):
                return m.group(0).rstrip(".")
    for email in _EMAIL_RE.findall(" ".join(lines)):
        if re.search(r"transport|bus", email.split("@")[0], re.I):
            return email.rstrip(".")
    return None


def _is_question(line: str) -> bool:
    return line.endswith("?") or (line.endswith(":") and len(line) <= 80)


def _faq_answer(lines: list[str], i: int, wanted: re.Pattern | None = None) -> str | None:
    """The answer under the question at line `i`: the next line, or with
    `wanted`, the first of the next three that matches it."""
    for follow in lines[i + 1 : i + 4]:
        if _is_question(follow):
            return None
        if wanted is None or wanted.search(follow):
            return follow
    return None


def _delay_policy(lines: list[str]) -> str | None:
    kept: list[str] = []
    for i, line in enumerate(lines):
        if _is_question(line):
            if _DELAY_QUESTION_RE.search(line) and (answer := _faq_answer(lines, i)):
                kept.append(answer)
            continue
        sentences = _sentences(line)
        first = next((n for n, s in enumerate(sentences) if _DELAY_RE.search(s)), None)
        if first is not None:
            kept.append(" ".join(sentences[first:]))
    return " ".join(dict.fromkeys(kept)) or None


def _lost_items_policy(lines: list[str]) -> str | None:
    for i, line in enumerate(lines):
        if _is_question(line) and _LOST_QUESTION_RE.search(line):
            if answer := _faq_answer(lines, i, re.compile(r"driver|lost|found|left", re.I)):
                return answer
        elif re.search(r"\b\d+ days\b", line) and re.search(r"driver", line, re.I):
            return line
    return None


def _late_bus_policy(lines: list[str]) -> str | None:
    """What a paragraph about getting home after activities says, from its
    first sentence on the subject. One that ends "...call during the times
    noted below:" carries on to the line with the number. A FAQ's question
    and a sentence about things left on a late bus don't count."""
    kept: list[str] = []
    for i, line in enumerate(lines):
        if line.endswith("?"):
            continue
        sentences = _sentences(line)
        # A heading ("Late Bus", "Activity Bus Information") isn't a sentence.
        # Nor one that points back at a list of rules ("...will adhere to these same rules": Cinnaminson).
        first = next(
            (n for n, s in enumerate(sentences)
             if _LATE_BUS_RE.search(s) and s[-1] in ".!?:" and not _LOST_QUESTION_RE.search(s) and "left" not in s and not re.search(r"\bthese (?:same )?rules\b", s, re.I)),
            None,
        )
        if first is None:
            continue
        hits = sentences[first:]
        kept.extend(hits)
        if hits[-1].endswith(":"):
            for follow in lines[i + 1 : i + 4]:
                kept.append(follow)
                if _PHONE_RE.search(follow):
                    break
    return " ".join(dict.fromkeys(kept)) or None


def _ednet_staff(html: str) -> list[dict]:
    """A department's Staff page on Educational Networks: one
    `.staff-categoryStaffMember` per person, either a table row (name,
    position, mailto: Winslow) or a photo card's dt/dd with no address
    (Burlington City; the profile link opens a form)."""
    soup = BeautifulSoup(html, "lxml")
    people = []
    for card in soup.select(".staff-categoryStaffMember"):
        cells = card.find_all("td")
        name_el = card.select_one("dt") or (cells[0] if cells else None)
        title_el = card.select_one("dd") or (cells[1] if len(cells) > 1 else None)
        mail = card.select_one("a[href^='mailto:']")
        name = _text(name_el)
        if name:
            people.append({"name": name, "title": _text(title_el) or None, "email": mail["href"][len("mailto:"):].strip() if mail else None})
    return people


def parse_department_page(pages: dict[str, str], page_urls: dict[str, str]) -> dict:
    """`pages`: the department's main page, and optionally its "staff" and
    "guidelines" (regulations) pages. Every field is read from the pages'
    content containers only; a page without one contributes nothing."""
    result: dict = {
        "office_phone": None, "office_fax": None, "office_hours": None, "office_address": None, "contacts": [],
        "delay_policy": None, "late_bus_policy": None, "late_bus_contractors": [], "bus_stop_change_procedure": None,
        "bus_stop_change_deadline": None, "bus_stop_change_form_url": None, "lost_items_policy": None,
        "daily_buses_note": None, "office_email": None, "main_url": page_urls["main"], "late_bus_url": None,
        "guidelines_url": page_urls.get("guidelines"), "lost_items_url": None, "closing_info_url": None,
    }
    boxes = {key: box for key in ("main", "guidelines") if pages.get(key) and (box := _content_box(pages[key])) is not None}
    lines = [line for box in boxes.values() for line in _lines(box)]
    if not lines:
        return result

    result["daily_buses_note"] = next((line for line in lines if _DAILY_BUSES_RE.search(line)), None)
    # A school whose daily buses are another district's has no office of its own to call about them.
    if not _other_district_buses(result):
        result["office_phone"] = _office_phone(lines)
        result["office_email"] = _office_email(lines)
    result["office_fax"] = _office_fax(lines)
    result["office_hours"] = _office_hours(lines)
    result["office_address"] = next((line for line in lines if _ADDRESS_RE.match(line)), None)
    result["delay_policy"] = _delay_policy(lines)
    result["late_bus_policy"] = _late_bus_policy(lines)
    result["lost_items_policy"] = _lost_items_policy(lines)
    result["contacts"] = _ednet_staff(pages["staff"]) if pages.get("staff") else []

    for box in boxes.values():
        for a in box.find_all("a", href=True):
            if _STOP_FORM_RE.search(a.get_text(" ", strip=True)):
                result["bus_stop_change_form_url"] = urljoin(page_urls["main"], a["href"])
                break
        if result["bus_stop_change_form_url"]:
            break
    return result


async def _discover_ednet_transportation(main_url: str, main_html: str) -> dict:
    """Educational Networks: the department page's left-hand menu
    (`#pageAsideWrapper`) links its Staff and Regulations pages."""
    aside = BeautifulSoup(main_html, "lxml").find(id="pageAsideWrapper")
    links = [(a.get_text(" ", strip=True).lower(), urljoin(main_url, a["href"])) for a in (aside.find_all("a", href=True) if aside else [])]
    staff_url = next((u for t, u in links if t == "staff"), None)
    guidelines_url = next((u for t, u in links if re.search(r"regulation|guideline|rules", t)), None)
    pages = {"main": main_html}
    if staff_url:
        pages["staff"] = await _fetch_edlio_page(staff_url)
    if guidelines_url:
        pages["guidelines"] = await _fetch_edlio_page(guidelines_url)
    return parse_department_page(pages, {"main": main_url, **({"guidelines": guidelines_url} if guidelines_url else {})})


# What each layout is expected to yield; a run that misses one warns.
_REQUIRED = {
    "finalsite_tree": ("office_phone", "delay_policy", "late_bus_contractors"),
    "eschoolview": ("office_phone", "delay_policy"),
    "edlio": ("office_phone",),
    "department_page": ("office_phone",),
}


def _other_district_buses(info: dict) -> bool:
    return bool(info.get("daily_buses_note") and _OTHER_DISTRICT_BUSES_RE.search(info["daily_buses_note"]))


def missing_fields(reader: str, info: dict) -> list[str]:
    if _other_district_buses(info):
        return []  # there's no office number of its own to find
    missing = [k for k in _REQUIRED[reader] if not info.get(k)]
    # A department that asks to be emailed (Voorhees, Eastern) is reachable without a number.
    return [k for k in missing if not (k == "office_phone" and info.get("office_email"))]


def has_answers(row) -> bool:
    """Whether a stored department gives a parent anything to act on: a
    way to reach the office, or who runs the buses instead. A row with
    none (a layout nothing could read) shows as no data at all, not as
    "call the transportation office" with no number."""
    return bool(row.office_phone or row.office_email or row.daily_buses_note)


async def discover_transportation(transportation_url: str, base_url: str) -> tuple[str, dict]:
    """Fetches the department's pages and returns which layout they were
    read as, with every parsed field plus the page URLs themselves (for
    "read the full policy" links)."""
    reader, info = await _discover(transportation_url, base_url)
    return reader, {"daily_buses_note": None, "office_email": None, **info}


async def _discover(transportation_url: str, base_url: str) -> tuple[str, dict]:
    main_url = transportation_url.rstrip("/")
    if main_url.lower().endswith(".aspx"):
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}) as client:
            resp = await client.get(main_url)
            resp.raise_for_status()
        return "eschoolview", parse_eschoolview_page(resp.text, main_url)
    if "/apps/pages/" in main_url:
        # Edlio (Medford) and Educational Networks share the URL shape; only Edlio has #content_main.
        html = await _fetch_edlio_page(main_url)
        if BeautifulSoup(html, "lxml").find(id="content_main") is not None:
            return "edlio", await _discover_edlio_transportation(main_url, html)
        return "department_page", await _discover_ednet_transportation(main_url, html)
    pages: dict[str, str] = {}
    pages["main"] = await _fetch_page(main_url)
    # Cherry Hill's tree: the main page links its fixed subpages. Anything
    # else is one page (Waterford), and asking for the subpages there only
    # fetches the site's not-found page.
    if f"{urlparse(main_url).path}/{_SUBPAGES['late_bus']}" not in pages["main"]:
        return "department_page", parse_department_page(pages, {"main": main_url})
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
    return "finalsite_tree", result


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
