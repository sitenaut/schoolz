# eSchoolView / LINQ (ASP.NET .aspx)

Mount Laurel Township. Mega-menu on every page; scope selectors to the school.

Per-district notes moved out of `docs/ONBOARDING_CRAWL_GUIDE.md` so a crawler loads only the platform it is looking at. Same rules: when you confirm a new shape, add it here in the same PR.

- **Mount Laurel Township (eSchoolView / LINQ, ASP.NET `.aspx`)** — 8 schools,
  `backend/seed/mount_laurel.json`. Not Finalsite, so none of the Finalsite
  selectors apply. What to know:
  - Every page repeats the whole **mega-menu**, and `#maincontent` is empty in
    the static HTML (client-filled), so any unscoped anchor/text scan reads the
    entire district's menu. School home pages are `/<slug>_home.aspx`; assets
    live under `/sysimages/Logos/<Name>.png` (page-relative in the header).
  - **Calendars**: each school (and the district, Harrington events/sports)
    exposes a public Google Calendar ICS, so the generic `district_calendar`
    scan works with no code. Find the feed id on the school's calendar page.
  - **Staff**: the home page links "Staff Directory"; `staff_roster.
    _fetch_eschoolview_roster` follows it and `_parse_eschoolview_page` reads
    `.scName` ("Last, First") beside `.scTitle`. No emails/phones/ids (the
    profile link opens a contact form), identity is name+title. Principals,
    nurses and counselors classify fine.
  - **School info**: footer is three plain lines (street / "City, NJ zip" /
    "Phone: ..."), parsed by `school_info._parse_eschoolview_footer`; taken
    only when the site URL ends in `.aspx`.
  - **Lunch**: SchoolCafé, but the school names there are hand-typed
    ("Mt Laurel", "Elem"). `schoolcafe.match_school` normalizes `mt`→`mount`
    and falls back to a unique whitespace-squashed match with `elem`→
    `elementary`; 8/8 matched.
  - **Documents**: `documents.scan`'s landing-page crawl drowned in the
    mega-menu (18 unrelated PDFs per school). For `.aspx` sites
    `school_documents._find_eschoolview_handbooks` takes only direct
    Google Doc/PDF links whose own text says "handbook" and never crawls.
    Some schools (Hartford) simply publish none.
  - **Transportation**: one server-rendered page (`/Transportation.aspx`),
    set as `District.transportation_url`; `transportation.parse_eschoolview_page`
    (selected by the `.aspx` suffix, plain httpx) reads office phone/fax/
    address/hours, staff ("Name - Title"; emails are Cloudflare `data-cfemail`
    on a span, decoded), and the policy sections by their all-caps headings.
    No late-bus contractor table exists, so the scan does not warn on that.
  - **Rotation**: Harrington Middle runs A/B/C days (`A-DAY`/`B-DAY`/`C-DAY`
    in its Google Calendar feed, already imported, but as plain events: the
    rotation regexes only know `Day N`). Hillside's "Letter Day Schedule" is a
    4-day A-D cycle published as one image-calendar PDF per month on an
    article page linked from its home page; `documents.scan` follows that
    link (`school_documents._find_letter_day_page`) and stores the PDFs as
    `letter_day_schedule` documents. The letters are drawn into the image, so
    nothing is parsed. Other elementaries may do the same (not checked).
  - **Gaps**: no newsletters found (each school has an ArticleArchive news
    page, not wired), letter days are not parsed into Today, athletics only via the ICS,
    no before/after care, absence is phone-only everywhere
    (unverified for Hartford/Larchmont/Springville), the PTO/district ICS
    feed was skipped.
