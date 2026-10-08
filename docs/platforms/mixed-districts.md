# Multi-platform district groups

Groups of districts onboarded together that span several platforms, so they do not belong to one CMS file. Sterling group: Sterling, Somerdale, Stratford, Magnolia, Laurel Springs (Presence, Edlio, Finalsite, WordPress). Eastern/Overbrook group: Gibbsboro, Berlin Borough, Berlin Township, Clementon, Pine Hill, Lindenwold.

Per-district notes moved out of `docs/ONBOARDING_CRAWL_GUIDE.md` so a crawler loads only the platform it is looking at. Same rules: when you confirm a new shape, add it here in the same PR.

- **Sterling Regional HS district + its four sending districts** (Somerdale,
  Magnolia, Stratford incl. Hi-Nella's students, Laurel Springs) —
  `backend/seed/{sterling,somerdale,stratford,magnolia,laurel_springs}.json`.
  Five districts, four platforms:
  - **Presence (ex-SharpSchool / "Smart Sites")** — Sterling and Somerdale
    Park. Answers plain HTTP but **headless Playwright gets 502s or
    `ERR_ABORTED`, so every scraper-based scan hangs: use httpx.**
    `staff_roster` has Presence parsers (table pages for Sterling with
    emails, a search JSON for Somerdale without), `school_info` reads the
    footer, `discover_from_website` in `school_documents` fetches over httpx.
    Sterling's SchoolCafé shortname is `SterlingHighSchoolNutriServe`,
    athletics is Arbiter 22533. Somerdale's SchoolCafé district exists with
    zero sites, so the shortname is null.
  - **Presence "Documents" widgets are invisible to a crawl.** A page's file
    list is not in its HTML: an inline `new ContentItemListUI('<folderId>',
    null, '[]', {"ContextId":...})` makes the browser POST the folder id and
    that settings dict (as a JSON *string*, `searchVal: ""`) to the anonymous
    `/portal/svc/ContentItemSvc.asmx/GetItemList`. A "page has no links" result
    on a Presence site means nothing until you've listed its widgets
    (`services/presence_documents.py`). Somerdale's menus (`/departments/
    cafeteria`: Sept PDFs, Oct JPGs; regular lunch, Pre-K lunch, Pre-K
    breakfast), 2026-27 calendar PDF (`/parents/school_calendars`, whose
    sidebar is the only source of marking periods and interim dates), bell
    schedule and Pre-K handbook all live only there. Wired as
    `School.presence_menu_page_url` -> `presence_menu.scan` (school-scoped
    `LunchMenu`; Pre-K lunch is skipped as a near-copy of the plain menu,
    Pre-K breakfast is kept and labelled because it's the school's only
    breakfast; menu *pictures* go to Claude as image blocks), and the marking-
    period scan reads the calendar PDF when the tracked page is Presence.
    Their file host 403s a default httpx User-Agent. Sterling's widgets hold
    only board notices/bids/policies, so nothing was missed there.
  - **Edlio/Educational Networks** — Stratford (`stratford.k12.nj.us`).
    `_parse_ednet_page` now also reads table-style staff lists; the footer is
    `.enf-address` (`school_info._parse_edlio_footer`). Calendar is
    `ICalServlet?id=0`; Yellin's bell PDF is stored (regular + early
    dismissal; the delayed-opening table is too irregular, flat time only).
  - **Finalsite** — Magnolia. Plain-page staff tables with Cloudflare-
    obfuscated emails (decoded in `staff_roster`). Finalsite ICS ids 2 and 3
    are duplicates, and the feed carries staff-only "Faculty Meeting" rows.
    Policy-folder child links are not handbooks (`school_documents` skips
    them). Lunch PDFs have yearless names (`OCTLUNCHMENU.pdf`) — year is
    inferred in `lunch_menu.py`.
  - **WordPress** — Laurel Springs: faculty cards parsed from the page,
    calendar from a PDF (its public Google Calendar only holds 2020/2023
    events — don't wire it), lunch PDF holds breakfast and lunch on separate
    pages. `school_info.scan` warns here, so address/phone live in the seed.
    The faculty page and the principal's-message page name different
    principals.
  - **Cross-cutting**: the NJ DOE CSV is stale for Somerdale (still lists the
    new superintendent as principal). `staff_roster`/`documents` scans never
    prune, so changing an id scheme leaves stale rows.
  - **Marking periods** (checked by crawling each site, not just the first
    pass): Sterling's are already in its ICS feed (Progress Reports, Report
    Cards, semester end) so no scan. Stratford and Laurel Springs print them in
    the school-year calendar PDF (`marking_period_url` = the site / calendar
    page; `find_calendar_pdf` follows the linked PDF, `parse_calendar_pdf_dated`
    reads "1st: 9/2/26-11/11/26" ranges plus INTERIMS / REPORT CARDS columns
    for Stratford, and trimester ends + a REPORT CARDS date list for Laurel
    Springs). Magnolia is on trimesters but publishes no dates anywhere (calendar
    PDF, handbook, ~120 crawled pages), so there is nothing to scan.
  - **Gaps**: no transportation on any of the five; newsletters
    are one-off PDFs (Sterling) or Smore links inside news posts (Stratford,
    no stable archive); PTAs are Facebook groups or empty PTBoard sites;
    Stratford has no athletics link and no staff emails (profile pages are a
    contact form); no Hi-Nella school exists (it only appears in `towns`).

- **Eastern's and Overbrook's sending districts, plus Lindenwold** — Gibbsboro
  and Berlin Borough (K-8, high school at Eastern), Berlin Township and
  Clementon (K-8, high school at Overbrook in Pine Hill), Pine Hill (K-12, runs
  Overbrook) and Lindenwold (K-12, no sending partners). Seeds
  `backend/seed/{gibbsboro,berlin_borough,berlin_township,clementon,pine_hill,lindenwold}.json`.
  Pine Hill's `towns` lists Berlin Township and Clementon. Hi-Nella has no
  school; it is a town on Stratford and Sterling.
  - **Check that the scan works, not that the source exists.** The first pass
    confirmed each feed and shortname by hand and still shipped five broken
    scans, found only by importing locally and running every job: a staff
    directory at a path the scan never tries, a SchoolCafé site whose name the
    matcher couldn't pair, a calendar page whose "calendar PDF" was a budget, a
    calendar page still linking last year's PDF first, and a marking-period
    layout no parser read. Import locally and run-now every job before calling
    a district onboarded.
  - **Don't read filenames out of a whitespace-splitting grep.** `[^" ]*\.pdf`
    turned "User Friendly Budget 26-27.pdf" into `26-27.pdf`, which read as a
    calendar. Print the whole href and the link text.
  - **Legacy Finalsite calendar feed** (Gibbsboro, Pine Hill):
    `/cf_calendar/feed.cfm?type=ical&feedID=<32 hex>&isgmt=1` is one feed for
    every calendar on the site. The newer `/fs/calendar-manager/events.ics`
    ids and `feed_id` on the same sites answer with zero events.
  - **Incident IQ public calendars** (Pine Hill's "Facility Events Calendars",
    `services/incidentiq.py`): the page body is empty until a widget loads 2-3
    seconds in, so a fetch that returns at DOM-ready sees nothing. Watch the
    network instead: the widget POSTs a `ViewId` to
    `https://<tenant>.incidentiq.com/api/event/events` with no login and gets
    the events as JSON in a hidden input. Stored in `ics_feeds` as
    `.../api/event/events?ViewId=<guid>` with a `school_slug`. They are room
    bookings, so community rentals sit beside school events. The district-wide
    view is the union of the school views; wiring it too would turn every
    school-scoped event into a district one.
  - **Menus in Google Drive** (`lunch_menu._resolve_drive_links`): Gibbsboro
    embeds each menu as a Drive viewer iframe, so the page has no filename; the
    Drive page's own title has it and `/uc?export=download&id=` serves the bytes.
    Clementon's page is a month/breakfast/lunch table of "PreK / K-8" Drive
    links with useless titles, so month and meal come from the cell
    (`_classify_menu_table`); its SchoolCafé district exists with zero sites.
    Berlin Township's are `October-Lunch-Menu.pdf` (no year, hyphenated).
  - **Staff directories are found from the school's own nav** when no fixed
    path works (`staff_roster.find_directory_links`, same host only):
    Lindenwold's are `/our-school/<school>-staff-directory` (names and emails,
    no titles), Gibbsboro's a "Staff Member | Position" table with
    "Last, First" names.
  - **Berlin Township (WordPress, Beaver Builder grid, Cloudflare)**: one
    `/staff-directory/` page lists the whole district; the school each person
    works at ("Location(s)") and the email are only on their own
    `/staff-member/<slug>/` page, so the scan reads every profile (cached 6h,
    shared by both schools) and `drop_sibling_school_staff` splits on location.
    Plain HTTP serves emails Cloudflare-obfuscated (`data-cfemail`). The site
    answers plain requests from some networks and challenges others; the
    sitemap (`/sitemap_index.xml`, named in robots.txt) needs a real browser.
  - **Marking periods printed as a grid** (Pine Hill's calendar PDF,
    `marking_period.parse_marking_period_grid`): a block per level, labels on
    one line and ranges on the next. A block named for buildings rather than a
    level is taken as elementary.
  - **SchoolCafé names**: "School Five" is "School 5" there, and "Elem" is a
    level word. Lindenwold's Early Childhood Center is "Lindenwold Preschool",
    which nothing matches.
  - **Gaps**: no absence method, bell periods, newsletters or PTAs for any of
    the six; no staff directory for Overbrook, Pine Hill Middle or Berlin
    Community (it lists administrators only); Berlin Township breakfast (the
    PDF name carries no month); no handbooks found for Gibbsboro or Berlin
    Township; Clementon's footer isn't parsed, so address and phone live in
    the seed.
