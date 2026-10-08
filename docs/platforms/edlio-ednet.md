# Edlio CMS and Educational Networks / SchoolSitePro

Haddon Heights, Medford Township, Medford Lakes, Mount Ephraim, Runnemede. Same family: `/apps/pages|staff|events|news/`, client-rendered page content, names-and-titles-only rosters.

Per-district notes moved out of `docs/ONBOARDING_CRAWL_GUIDE.md` so a crawler loads only the platform it is looking at. Same rules: when you confirm a new shape, add it here in the same PR.

- **Educational Networks / SchoolSitePro (Haddon Heights; Barrington is the same
  CMS)** — `backend/seed/haddon_heights.json`. Recognizable by the generator
  meta "Educational Networks / SchoolSitePro" and `/apps/...` URLs (`/apps/staff/`,
  `/apps/events/`, `/apps/bell_schedules/`, `/apps/news/`). Not Finalsite, so
  `school_info.scan` finds no `.fsLocationAddress` and warns
  `school_info_missing_fields` — type address/phone/hours into the seed (the
  footer `.enf-address`/`.enf-phone` has them). Per-school sites are
  subdomains of the district domain. **Staff**: `/apps/staff/` is one
  `.staff-category` per department, each card a name (`dt`) and optional title
  (`dd`); profile pages are email *forms*, so the roster
  (`staff_roster._parse_ednet_page`, plain httpx, tried before the Finalsite
  paths) has no emails or phones. Published emails live only on hand-typed
  pages (Haddon Heights's "Nurse Information"). **Calendars**: the public
  `/servlet/ICalServlet?id=N` feeds (ids are enumerable, ~0-12) return 0 events
  without a browser User-Agent on per-school subdomains — use the `www` host.
  An empty school feed (the high school's) is real, not broken. **Bell
  schedules** at `/apps/bell_schedules/` list Full day / Half day / Two-hour
  delay per audience. Haddon Heights's Jr/Sr High varies by weekday (Wed/Thu
  are 4-block days) and `bell_periods` holds only one `regular`, so only
  Mon/Tue/Fri is stored. **Newsletters**: each school's `/apps/news/` page
  posts issue links; Glenview's are Smore (tracked as `smore_archive` on that
  page), Atlantic's are Canva links (nothing to scan). **Lunch** is SchoolCafé
  (Nutri-Serve; ISD shortname via `GetISDByShortName`), but Glenview and
  Seventh publish breakfast only there — no lunch entrées, so no lunch card.
  Parent absence reporting is only "call, or email the school's administrative
  assistant" (Family Handbook), so the seed sets `absence_method: phone`
  with that instruction rather than a guessed address.

- **Medford Township (Edlio CMS, `*.medford.k12.nj.us`)** — 5 elementaries,
  Haines 6th Grade Center, Memorial Middle; `backend/seed/medford.json`. Its
  high school is Shawnee (Lenape Regional), so the Lenape district's `towns`
  now lists all its sending towns (Evesham, Medford, Medford Lakes, Mount
  Laurel, Shamong, Southampton, Tabernacle, Woodland) in
  `evesham_lenape.json`; towns are per district, so a Medford family sees all
  four Lenape schools, not just Shawnee. Medford Lakes is a separate K-8
  district, not yet onboarded.
  - **Platform tell**: generator meta "Edlio CMS", `/apps/pages|staff|events|news/`,
    files on `*.files.edl.io`, emails as Cloudflare `data-cfemail`.
  - **Calendar**: `/apps/events/ical/?id=N` on the district host (0 = district,
    1-7 = schools; school feeds repeat the district events, which
    `district_calendar_scan` subtracts). The `/apps/events/` HTML 403s and
    `/servlet/ICalServlet` is the older ednet pattern, not this one.
  - **Staff**: `staff_roster._parse_edlio_page` (`li.staff`, names + titles only;
    the email link is a form). Chained after the ednet parser.
  - **School info**: `school_info._parse_edlio_footer` (`.footer-info-block`
    address/phone). Headers are text-only, so there is no logo to find.
  - **Transportation**: `transportation_url` is any page of the department;
    `parse_edlio_transportation` finds Staff and Guidelines from its menu by
    link text. The guidelines page's sections are collapsible blocks, not
    headings. No late-bus or delay pages exist, so the scan only requires a phone.
  - **Rotation ("What Day is It?")**: the district home page links a Drive PDF of
    monthly A-D grids for the elementary schools. The link is injected
    client-side (invisible to plain GET) and its file id changes when the sheet
    is replaced, so `documents.scan` renders the district home page, matches the
    link text (`letter_day_schedule`), and attaches it to every elementary
    school (`discover_district_letter_days`, cached 6h; only what a run found
    stays current). Linked, not parsed: the rotation machinery is digit-only
    ("Day N"; `StudentSpecial.rotation_day` is an integer), same gap as
    Hillside and Harrington.
  - **Lunch**: SchoolCafé `MedfordTownshipSDNutriServeMETZ`; "6th" now
    normalizes to "sixth" so Haines matches (7/7).
  - **Hours** come from one District "School Hours" page in three groups
    (Haines+Memorial, Cranberry Pines+Taunton Forge, Allen+Kirby's Mill+
    Chairville), typed into the seed. **Absence** is a per-school phone line
    plus an email for four schools; the Haines address resolved to
    `memorialattendance@`, which may be shared.

- **Medford Lakes (Edlio CMS, one shared site `www.medford-lakes.k12.nj.us`)** —
  Nokomis (PreK-2) and Neeta (3-8), seed `backend/seed/medford_lakes.json`.
  - **One website for both schools**: both School rows carry the district URL,
    so every per-school scan reads the same pages. `school_info.scan` can't
    parse that footer (it lists both schools' addresses, `_parse_edlio_footer`
    wants one) and warns every run; address, phone and hours are typed into
    the seed, and `ensure_location` still geocodes them for weather. Disable
    those two jobs if the warning is noise. No logo is found either.
  - **Calendar**: Edlio's iCal servlet, `/servlet/ICalServlet?id=0` (not
    `/apps/events/ical/` like Medford Township). One district feed, ~80 items.
  - **Pages are client-rendered**: `/apps/pages/...` content only exists after
    JS runs, so fetch with `wait_for_selector="#pageContentWrapper"`.
    `school_documents._find_doc_file_anchors` scopes to that container the
    way it does Finalsite's `#fsPageContent`.
  - **Documents**: the nav's "Policy, Procedure and Handbook" is a folder of
    board policies, so a "polic*" nav label without parent/student/family is
    not treated as a handbook. "District Calendars" is a *hub*: its district
    calendar and trimester PDFs are skipped and only the "2026-2027 6 Day
    Cycle Calendar" is kept, as a `letter_day_schedule` (the `N day cycle`
    pattern). The bell-schedule page lists both schools' PDFs; the scan keeps
    only each school's own (`keep_own_school_bell_schedules`) and they are
    still 2025-26, the latest published. Their periods are typed into the
    seed as `bell_periods`, with `delayed_opening_time` from the same PDFs.
    "My Food Days" is kept as a `lunch_ordering` document (see Gaps).
  - **The 6-day cycle is parsed** by `services/cycle_calendar.py` (pdfplumber
    word coordinates; see its docstring for the grid geometry) through the
    existing `hs_rotation.scan` job: when `District.hs_rotation_url` ends in
    `.pdf` it parses a cycle sheet instead. The sheet is *discovered* on every run
    (the district site's "District Calendars" hub, newest academic year wins,
    `pick_cycle_pdf`); the configured PDF is only the fallback if the site can't
    be read, because last year's PDF stays online and never 404s. Items are
    `Day N` rows (source `rotation_pdf`) for every school type
    in the district; X cells are closed days. A broken 1..N sequence records a
    `cycle_sequence_break` parse issue.
  - **Both schools share one roster page**, each listing the other's staff
    with the sibling school in the title. `staff_roster_scan` drops those
    (`drop_sibling_school_staff`) for schools sharing a `website_url`.
  - **NJ DOE contacts**: the state CSV is kept at `backend/seed/njdoe/` and
    `scripts/import_njdoe_contacts.py` copies a state principal email onto the
    matching roster principal only when it contains the person's surname. Only
    one real email (the principal's) was obtainable this way.
  - **Absence** is prompt #2 on each school's main number, voicemail from
    4:00 PM the evening before until 8:30 (Neeta) / 8:40 (Nokomis).
  - **Gaps**: lunch is My Food Days (Blazor app behind a parent login, no public
    menu API, so only the link is kept; no SchoolCafé); newsletters are Constant Contact (`conta.cc`) links with no
    archive page; staff directory has names and titles only (no emails but the
    principal's); no transportation page; Lenape's
    seed already lists Medford Lakes as a sending town.

- **Mount Ephraim (Edlio CMS, `www.mtephraimschools.com` + a subdomain per
  school)** — Mary Bray (PreK-2/elementary) and Raymond W. Kershaw (middle),
  K-8; grades 9-12 go to Audubon HS, so `audubon_barrington.json` lists
  "Mount Ephraim" in Audubon's `towns`. Seed `backend/seed/mt_ephraim.json`.
  - **Calendar**: `/apps/events/ical/?id=N` on the district host, as at Medford
    Township: 0 = district (only 3 items), 1 = Mary Bray, 2 = Kershaw
    (`school_slug` feeds, ~240 and ~120 items).
  - **Lunch**: SchoolCafé `MOUNTEPHRAIMPSNUTRISERVE` (the obvious `...SD...`
    guesses are empty). Its two sites are both typed "Elementary", so
    `match_school` gained a last-resort match on name tokens minus level words
    and middle initials ("Raymond W. Kershaw Middle" = "Raymond Kershaw
    Elementary"). The food page's own menus are Drive PDFs, not used.
  - **Per-school websites**: each school has its own Edlio subdomain
    (`mbe.`/`rkm.`), so `school_info`, staff and documents scans work as for
    Medford Township (staff 25-47 per school, names and titles only).
  - **Gaps**: bell times (the Mary Bray schedule is a Google Sheet that needs a
    sign-in; none published for Kershaw), absence method (Red Rover is the
    staff tool; nothing public for parents), no newsletters, no logos,
    transportation. Kershaw's footer prints its ZIP as `8059`, which
    `school_info.scan` writes back over the seed's `08059`.

- **Runnemede Public School District** (3 schools: Bingham and Downing PreK/K-3,
  Volz PreK-8 tracked as `middle`; one Educational Networks / SchoolSitePro site,
  `runnemedeschools.org`) - `backend/seed/runnemede.json`. Its high school is
  Triton (Black Horse Pike Regional), a separate district, not onboarded.
  - **Crawl method that found things**: render every `/apps/pages/` link from the
    home page and *both school menus* through the scraper and list `iframe[src]`
    as well as anchors. The plain home page has a school's sub-menu in static
    HTML, but page *content* is client-rendered (`#pageContentWrapper`).
  - **School `website_url` is the school's own page** (`/apps/pages/index.jsp?
    uREC_ID=<id>&type=d`; Bingham and Downing share one), not the district root:
    its menu carries Handbooks / Pre-K Handbook / a bell-schedule link that the
    root nav lacks. `school_documents.discover_from_website` and
    `staff_roster._fetch_ednet_roster` therefore resolve links/`/apps/staff/`
    against the origin when the URL has a query. `school_info.scan` warns each
    run (no school footer); address/phone/hours are typed in from the district
    Contact page, and the scan still geocodes.
  - **Roster is district-wide** (`/apps/staff/`, ~128 people, titles only, no
    emails), so every school shows everyone. Each school also has its own
    hand-typed "<School> - Staff Directories" page (`uREC_ID=622246/7/8`,
    server-rendered, same `.staff-categoryStaffMember` markup) linked from
    Parent Resources / Teachers & Staff Websites, *not* from the school menu.
    Per-school rosters would need a `staff_directory_url` field - not built.
  - **Calendars**: `/servlet/ICalServlet?id=0` is only a stock US-holiday feed
    (Tax Day, Cinco de Mayo) - **not wired**. The detailed calendars are
    **embedded Google Calendars** (`iframe src=...calendar/embed?src=<id>`): one
    shared by Bingham & Downing on their school page (district-scoped feed with
    `school_types: ["elementary"]`, so it shows on both and not Volz) and Volz's
    own on its "Calendar" sub-page (`school_slug: volz`); fetched as public iCal,
    ~5k events incl. history. The district's printed calendar is a one-page PDF on
    a Google Drive link in the nav; a Drive `uc?export=download&id=<fileId>` URL
    serves the bytes anonymously and `district_calendar_pdf.fetch_pdf` accepts a
    URL that is itself the PDF, so it is `District.calendar_pdf_url`. **Next year
    the nav link has a new file id** - re-copy it. The Buildings & Grounds page
    embeds a facilities-use calendar (building rentals, not wired).
  - **Lunch**: no SchoolCafé match; one district-wide monthly PDF on
    `/apps/pages/index.jsp?uREC_ID=619036` named `OCTOBER  2026  Menu.pdf`
    (double spaces, `%20%20` in the href, site-relative, newer files carry
    `?rnd=`). `_MONTH_YEAR_RE` tolerates `%20`/whitespace, and discovery accepts
    `.pdf?query` hrefs and joins relative ones to the page URL.
  - **Hours**: Bingham/Downing's page has K-3 and Pre-K hours, a 90-minute delay
    (doors 9:45-10:00, late after 10:00) and early dismissal (K-3 12:45, Pre-K
    12:20-12:30); flat fields use K-3. Volz's are on its own "School Hours &
    Directions" sub-page (4-8: 7:45-2:15, "One Session" until 12:00, preschool
    8:30-2:30 / 12:15) and its period table is a Google Slides deck (found by
    `documents.scan` as `bell_schedule`; `/export/txt` gives text with the slide
    titles detached from their blocks - tell delay / early / full day apart by
    the times): `bell_periods` regular, early_dismissal, delayed_opening
    (delay starts 9:15). Bingham/Downing publish no period table.
  - **Before & after care** (`School.sacc`): one district PDF on
    `/apps/pages/index.jsp?uREC_ID=619032` (file name changes yearly - the page
    is tracked as `handbook_url`). Hours differ by school (Volz AM ends 7:45),
    entrances differ, one district phone, fees and late-pickup charges. Fees go
    into `closures_notes` (no field for them). No before/after care on weather
    delay or early-dismissal days. Per-school site phones are not published.
  - **Documents**: Volz publishes Student, AI and Preschool handbooks (Google Docs) and
    Bingham/Downing a Pre-K handbook PDF; all found from the school pages.
  - **Absence**: phone, "press 1 and leave a message", per-school lines.
  - **Gaps**: Bingham/Downing newsletters are monthly Google Slides decks on a
    per-year page ("Newsletters 25 - 26"), which nothing scans; no ArbiterLive
    (Volz's sports schedules/locations are Google Docs, the games come through
    its calendar); PTA is Facebook-only (officer list is 2023-24); no
    transportation page; Pre-K / preschool hours aren't stored (one set of flat
    times per school); no Bingham/Downing bell periods.
