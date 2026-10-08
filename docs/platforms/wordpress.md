# WordPress (multisite and single)

Camden City, Haddonfield. Berlin Township and Laurel Springs are WordPress too: see mixed-districts.md.

Per-district notes moved out of `docs/ONBOARDING_CRAWL_GUIDE.md` so a crawler loads only the platform it is looking at. Same rules: when you confirm a new shape, add it here in the same PR.

- **Camden City (WordPress multisite, `camdencityschools.org`)** — 15
  traditional district schools (5 HS at/near the Camden High campus, 2
  early-childhood centers, 8 PreK/K-8 family schools); `backend/seed/
  camden_city.json`. Deliberately excludes Camden's separate Renaissance
  schools (KIPP Cooper Norcross, Mastery, Uncommon/Camden Prep) — those are
  independently-operated charter-like schools under a different district
  code, not this site.
  - **Platform tell**: WordPress (Beaver Builder/Genesis theme, Yoast SEO,
    "Modern Events Calendar", "ABCFolio Staff List" plugins) run as a
    multisite, each school at its own subpath on the same domain
    (`/chs/`, `/eastsidehs/`, `/cooperspoynt/`, ...) rather than a separate
    host per school.
  - **Cloudflare JS/Turnstile challenge on every page** — plain curl/httpx
    get a 403 "Just a moment..." interstitial even with a real browser
    User-Agent string; only a real browser (the Playwright scraper) gets
    past it. Go straight to the scraper here, don't burn a round-trip on
    plain HTTP first the way the crawl procedure otherwise recommends.
  - **Lunch: Aramark MySchoolPlate**, not SchoolCafé (the `CAMDENCITYPS`
    shortname exists but matches no school, so it only ever warned).
    `School.myschoolplate_location` = `camden/<location-key>`, found by
    matching the school's address against `services/myschoolplate.py:
    fetch_locations` - 14 of 15 matched on street number + first street word;
    Eastside had to be set by name. The site lists charters too (Mastery,
    Uncommon, Urban Promise) - skipped like the rest of the Renaissance
    schools. The four campus high schools share one location, so each gets the
    same menu. The vendor's own address for Eastside is the Mickle Street one,
    which supports the new-building reading of the address conflict below.
  - **Staff directories are documents, not pages** - 6 of the 15 link one
    from "About Us" (PDF tables for Eastside, Davis, Catto; an `.xlsx` for
    Veterans; a Google Slides deck for Cooper's Poynt), set as
    `School.staff_directory_url`. Forest Hill's and Creative Arts' directory
    pages are empty shells, Camden High has none (only a leadership page and
    an attendance contact), Dudley has nothing on its site. All of them are
    dated (2022-23 to 24-25): the rows carry no as-of date, so they read as
    current. Nurses come from each school's "Nurse's Corner" page instead
    (`role_pages.parse_inline_page`: "School Nurse <name> <phone>" in the page
    text, email accepted only if it contains her surname).
  - **Calendar**: tracked as the `/calendar/` page itself
    (`District.calendar_pdf_url`), not a dated PDF filename — no ICS feed
    found.
  - **Athletics**: Camden High and Eastside High resolve real ArbiterLive
    entity ids (3073, 26231) via the district's own "District Athletics"
    page; the three smaller campus HS (Brimm, Creative Arts, Big Picture)
    may share Camden High's athletics program in practice but that's not
    confirmed per-school, so left null.
  - **Address conflicts, kept as each school's own stated text rather than
    guessed**: Eastside's own subsite says 3100 Federal Street while the
    district's school-directory widget says 2800 Mickle Street (there's a
    live "Eastside High Construction Plans" page, so this plausibly reflects
    an old-vs-new building rather than a crawl error — worth a human check
    before trusting either). The shared Camden High campus building itself
    is given as zip 08103 by some of its five schools' own pages and 08104
    by others.
  - **Gaps**: no absence method/phone/portal beyond a generic "contact your
    school" plus an unconfirmed Genesis portal link (same ambiguity as
    Audubon/Collingswood — not written in with confidence); no
    early-dismissal/delayed-opening times or bell-period detail (only
    regular start/end times published); no marking periods, transportation,
    or HS rotation; no newsletter platform found at all (no `smore`,
    `resource-manager`, PTBoard, or Givebacks signal anywhere on the site).

- **Haddonfield School District** (5 schools, WordPress multisite, one
  subdomain per school; Genesis SIS) - `backend/seed/haddonfield.json`.
  `haddonfield.k12.nj.us` has a cert for the wrong host; the real site is
  `haddonfieldschools.org`.
  - **Calendar**: one embedded Google Calendar on `/calendars/` (id in the
    iframe `src`), fetched as public iCal - no code. A random second request
    to a school subdomain can return a bare Sucuri-style 403 from a plain
    client; retry rather than conclude the page is blocked.
  - **Lunch**: SchoolCafé `HADDONFIELDPSNUTRISERVE`. Only four sites are
    listed (the three elementaries + the HS); the middle school has none, so
    it gets no lunch rows (`schoolcafe_school_unmatched` warning each run).
  - **Staff**: every school's `/staff-directory/` (HS: `/staff-directory-2/`)
    is one TablePress table - section header rows (`.directory-letters`: a
    letter or a department), then name + `<i>title</i>` + a Cloudflare-
    obfuscated email icon. `staff_roster._parse_tablepress_directory`.
    `source_constituent_id` is 64 chars: a first cut keyed on the full
    name+title+department overflowed it and failed 3 of 5 schools.
  - **Newsletters**: the district page's Smore archive stops at June 2024
    (not tracked). Elizabeth Haddon's homepage links "Current Newsletter" as
    the bare short form `www.smore.com/<code>` (301 to
    `secure.smore.com/<code>`), which the issue-link regex used to miss
    (`smore_archive_no_issues`); other schools publish on ParentSquare or
    Google Docs.
  - **PTAs**: Central, Tatem, Middle, High resolve on Givebacks (found by
    guessing shortnames against `resolve_org` with an address match - the
    PTA's own link pointed at memberhub/an old domain). Middle's is
    `haddonfieldmiddleschoolpta`. HS (`hmhs`) is empty. Elizabeth Haddon's
    `ehspta.org` has no DNS and a stray `ehspta` shortname is a different
    school in Washington state - Facebook-only, nothing to scan.
  - **Athletics**: `haddonfieldathletics.org` is ArbiterLive white-label,
    entity 9260 (Middle and High share it).
  - **Gaps**: HS bell schedule is a login-gated Google Sheet (no times);
    Middle's per-grade bell tables (6/7/8 differ) are only stored as the flat
    start/end/early/delay times; absence is an email per school's attendance
    office; shared district logo only; `school_info.scan` warns every run
    (no address/phone in the WordPress footer, seed values are kept).
