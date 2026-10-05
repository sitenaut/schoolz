# Onboarding crawl guide

A checklist for onboarding a brand-new district/school into schoolz: what data
points to go looking for, on which pages, in what shape, and how to pull each
one out once found. Read this **before** starting a new onboarding pass, and
follow it as a literal crawl procedure — don't rely on memory of "how Audubon
worked," because the next district's platform choices will differ in at least
one axis.

This is a companion to CLAUDE.md's "Data sources and their quirks" section,
not a replacement — CLAUDE.md documents confirmed implementation detail per
source (the code that already exists); this doc is the **procedure**: where
to look for each data point on a school/district you haven't onboarded yet,
and which shape you're likely to find. When you confirm a new shape for
something already covered here, update this file in the same PR — that's the
whole point of keeping it.

## How to actually do a crawl

For each school and district site, in order:

1. Fetch the homepage and every top-level nav link (`Our School`, `About Us`,
   `Departments`, `Parents`, `Academics`) via the scraper
   (`scraper_client.fetch_html` / `POST /fetch-html`, `wait_for_selector="a"`
   is usually enough — most district CMSs, Finalsite included, server-render
   the page shell even when a widget inside it is client-rendered).
2. Grep the rendered HTML for these signal strings (case-insensitive) and
   follow every match: `smore`, `resource-manager`, `arbiterlive`,
   `arbiterwebsites`, `ptboard`, `givebacks`, `schoolcafe`, `calendar.google`,
   `.ics`, `bigteams`, `digitalsports`. Each one identifies a whole category
   below.
3. For any page that looks like a listing/archive (newsletters, events,
   bulletin board), don't just read the first link — check whether the
   listing itself is the stable thing to track (see "Track the page, not the
   link" below) before wiring a single URL.
4. When a link on the district's own site goes to a **white-labeled**
   platform (its own branded domain instead of the platform's own domain —
   `audubonathletics.com` instead of `arbiterlive.com`, `easternvikings.
   arbiterwebsites.com`), that branded site's own homepage almost always
   links back to the *real* platform URL somewhere (a "Calendar"/"Schedule"
   link) — fetch it and grep for the platform's real domain rather than
   assuming the branded domain is unsupported.
5. Plain `curl`/httpx first, the scraper (Playwright) only when the first
   attempt comes back empty or 502s. Confirmed real: Audubon's own
   attendance-calendar redirect 502'd repeatedly through the scraper
   container but succeeded immediately via plain httpx — some sites'
   anti-bot rules apparently treat a headless-browser fingerprint worse than
   a bare GET. If the scraper fails on a URL that looks like it should be
   simple (a redirect, a static page), retry with plain httpx before
   concluding the source doesn't work.

## Track the page, not the link

The single biggest recurring mistake this guide exists to prevent: **tracking
a URL that will go stale, instead of the stable page location that always
points at whatever's current.** Confirmed real, twice independently:

- A Smore newsletter issue URL (`app.smore.com/n/<code>`) changes every time
  a new issue is published — the school edits their *own webpage* to point
  at the new issue, but the literal issue link they had you track dies.
- A district's own PDF attendance-calendar URL (`resources.finalsite.net/
  .../AudubonCalendar26-27-*.pdf`) gets a new CDN hash every year — the
  wrapper page (`/about-us/2026-27-attendance-calendar`) that redirects to
  it is what stays linked from the nav.

Whenever a source is "the current issue of X" rather than "a fixed document,"
ask whether there's a stable page that resolves to the current one, and track
*that* instead. See "Newsletters" below for the concrete patterns.

---

## District & school basics

**Fields:** `District`/`School` name, address, phone, website_url, logo_url,
school_type, towns.

**Where:** the school's own homepage footer (`<footer>`, `.fsLocationAddress`
on Finalsite — the page has *two* `<footer>` elements, one hidden, so wait on
`.fsLocationAddress` specifically, not `footer`). Logo is the first `<img>`
in `<header>`, skipping a Google Translate badge some sites embed first.

**Method:** `services/school_info.py`, deterministic, already generic.
Nothing new to check per-district beyond confirming the site is Finalsite
(most Camden County districts are) — a non-Finalsite site (Barrington's
legacy "Educational Networks" CMS) needs the footer selector re-verified by
hand.

---

## Bell schedules

**Fields:** `School.start_time`/`end_time`/`early_dismissal_time`/
`delayed_opening_time` (flat summary strings) and `School.bell_periods`
(structured, `dict[variant] -> list[{name, start, end}]`).

**Where:** `/our-school/bell-schedule` is the confirmed URL pattern on
Finalsite sites with a dedicated page (Audubon's three schools all use it).
Elsewhere it may be embedded on a general "Our School" or "Parents" page
instead — search for "bell schedule" or "dismissal" text if the dedicated
path 404s.

**Also sometimes genuinely not published anywhere** — same finding as
Absence/attendance reporting below: a thorough per-school pass across all
11 Collingswood/Oaklyn/Woodlynne schools (Apptegy platform) found no
"Bell Schedule," "Hours," or "Dismissal" page or nav item anywhere. Don't
keep digging past a real nav-based search on this platform; a printed
handbook PDF not linked from the nav is the likely real source, out of
scope for a plain crawl.

**Shapes confirmed real:**

- **Single flat schedule** (most elementary schools): one arrival/dismissal
  time per schedule type. Populate the four flat fields directly.
- **Real `<table>` markup with grade-band columns** (Audubon HS: grades 7-8 /
  9-10 / 11-12 have genuinely different clock times for some periods, not
  just a different lunch slot). **Always fetch the raw HTML and find the
  actual `<table>` — do not trust a flattened/whitespace-collapsed text dump
  for a multi-column table.** A text extraction silently interleaves columns
  (confirmed: a `re.sub('<[^>]+>', ' ', html)` pass turned a 3-column table
  into garbled "Periods 4/5" labels that looked like combined blocks but
  were actually a *different, single-column* early-dismissal table). Parse
  with BeautifulSoup's actual `<td>` cells, not text-flattening.
- **Grade-banded storage**: populate `bell_periods["regular"]` with one
  representative band (whichever covers the most students, or the
  numerically middle band) for callers with no student context (the public,
  school-wide Today card), *and* `bell_periods["regular_grades_X_Y"]` for
  every band that actually differs (schemas.py's `_BELL_PERIOD_VARIANTS`
  needs the new band-suffixed keys added if this is a new split — follow the
  precedent of `long_block_delayed_opening`/`long_block_early_dismissal`
  from migration 0055, don't invent a new mechanism). A signed-in student's
  own captured schedule resolves its correct band automatically via
  `bell_schedule.period_name_by_start_time` (merges every band's start-time
  → label mapping) — no grade-detection needed, since `Student.grad_year`
  isn't even reliably set below 9th grade.
- Real typos happen in source tables (`"10:19 am - 1-:54 am"` — obviously
  meant `10:54`, given the stated "35 Minute Periods" rule). Correct the
  obvious value; note the correction doesn't need to survive as a comment
  once entered, since the derivation is checkable against the page directly.

**Verify:** after populating, sanity-check the merged/representative table
against the real page numbers by eye — the multi-column-table gotcha above
is the single easiest bell-schedule mistake to make.

---

## Lunch menus

**Fields:** `LunchMenu`/`LunchMenuItem` (district-scoped, per school_type +
meal_type) or `District.schoolcafe_shortname`.

**Where:** `/departments/food-services` (Finalsite pattern) or similar.

**Shapes confirmed real, check in this order:**

1. **SchoolCafé** (`schoolcafe_shortname`) — the food-services page links
   `schoolcafe.com/<SHORTNAME>/menus` directly with the shortname visible in
   the URL: easy, wire it straight in. If the page instead links the
   **generic** `schoolcafe.com/menus` with no shortname baked in, the
   district may still be on SchoolCafé but hasn't published a direct link —
   **verify against the real public API**
   (`https://webapis.schoolcafe.com/api/GetISDByShortName?shortname=X`)
   before guessing a shortname pattern from other districts' naming (tried
   ~15 plausible guesses for Audubon, zero hits — the district apparently
   isn't in SchoolCafé's public directory even though its neighbor
   Barrington, same vendor Nutri-Serve, resolved on the first real guess).
   Common patterns confirmed real across this codebase's districts:
   `<TOWN>PSNUTRISERVE`, `<TOWN>TWPPSNUTRISERVE`, `<TOWN>SDNUTRISERVE` — but
   treat these as a starting point to verify, not a rule.
2. **Direct district-published PDFs**, one per (grade band, meal type) per
   month, discovered by `services/lunch_menu.py`. Two real filename
   conventions exist:
   - Hyphenated (`September2026-ES-Lunch.pdf`) — the original, already
     handled.
   - No hyphens, spelled-out band, "...Menu" suffix
     (`September2026ElementaryLunchMenu.pdf`,
     `September2026JH-HSLunchMenu.pdf`) — also handled now (Audubon).
   A **new** convention needs its own regex added to
   `_classify_pdf_link`/`_PDF_FILENAME_RE2` rather than trying to force it
   into the existing pattern.
   **Also check whether the links on the page are direct `.pdf` hrefs or
   Finalsite `/fs/resource-manager/view/<uuid>` wrappers** — the latter
   needs `_resolve_resource_manager_links` to follow the redirect first; a
   plain `href=".pdf"` scan silently finds zero PDFs on a page that only has
   wrapper links.
3. **FD MealPlanner** (`fdmealplanner_location`) — a specific vendor
   (confirmed: Whitsons, Haddon Township). Its `/meals` endpoint answers a
   bare request with no auth; only the initial org lookup needs the
   client-side-encrypted token, a one-time thing at onboarding.
4. **School-scoped, no district pipeline** — `LunchMenu.school_id` set
   directly, for a school with none of the above (rare).
5. **One unbanded, all-grades PDF** (Evesham: `.../September_2026.pdf` on
   `/lunch-menu`). No grade band in the filename, so a bare month+year is
   taken as the menu for **every** school type the district has
   (`discover_current_menus(school_types=...)`, one parse shared across the
   types). Siblings such as `..._lunch_spreadsheet.pdf` /
   `..._breakfast_spreadsheet.pdf` are nutrition tables, not menus, and are
   skipped by `_NOT_A_MENU_RE`.
6. **Abbreviated month, two meals, Spanish twins** (Merchantville:
   `MERSept26LunchMenu_1.pdf`, `MERSept2026BreakfastMenu.pdf`, each with a
   `...SPA` twin) on `/cafeteria`. A school-code prefix is glued to a 3-letter
   month and a 2- or 4-digit year, so `_classify_abbreviated_pdf_link` finds the
   month by its first three letters and skips the `SPA` twin. Breakfast and
   lunch are kept separately (current month and later per meal) and fanned out
   to every school type, as in shape 5.

**SchoolCafé quirks:** the shortname can be misspelled by the vendor
(Lenape: `LenapeRegionlHighSDNutriServe`, no "a" in "Regional") — verify with
`GetISDByShortName`, don't correct it. A regional district may list one
site named after the district itself rather than one per school; when
`GetSchoolsList` returns exactly one site the scan applies it to all the
district's schools.

---

## District/school calendar (closures, early dismissals, holidays)

**Fields:** `SchoolContentItem` (scope=district or school) via
`District.ics_feeds` / `services/district_calendar.py`.

**Where and shapes, check in this order:**

1. **Finalsite calendar-manager widget** (`/fs/calendar-manager/events.ics?
   calendar_ids[]=N` or `?feed_id={uuid}`) — the most common pattern in this
   codebase's districts so far (Voorhees, Eastern, Cherry Hill). The widget
   **never puts this URL in the page HTML** — the "Subscribe" button hands
   it to `navigator.clipboard.writeText()` via JS. Found by scripting a real
   Playwright click and intercepting that write, not by guessing. Once
   found, `calendar_ids` are small sequential integers (1-2 are usually
   Finalsite's own sample/test calendars, skip them) — enumerable by trying
   a range once you have the base URL pattern.
   **A district may not expose this widget at all** (confirmed: Audubon's
   `/calendar` page returned only empty sample-calendar IDs on every guess)
   — don't sink much time guessing `calendar_ids` past a handful of
   attempts; move to the next shape.
2. **Embedded Google Calendar(s)** (confirmed real: Audubon, via an
   `<iframe src="calendar.google.com/calendar/embed?...">` on the school's
   own "Public Calendar" page — a page whose *name* gives no hint this is
   what it is). The calendar id(s) are base64-encoded in the iframe's `src`
   query string (`src=` param(s), decode with `base64.b64decode`, padded to
   a multiple of 4). Fetch as standard iCal:
   `https://calendar.google.com/calendar/ical/<urlencoded-id>/public/
   basic.ics` — this is a **plain public endpoint, no auth**, and the
   existing `services/district_calendar.py` (`fetch_district_calendar`)
   already parses any generic iCal URL with zero code changes needed, since
   it just uses the standard `icalendar` library. A school's calendar page
   may embed **two** Google Calendars — a school-specific one and a
   district-wide one — wire both, the school-specific one with
   `IcsFeed.school_slug` set.
   **This is a better source than a PDF calendar when both exist for the
   same content** — it's structured, covers a full year forward, and often
   includes items (Board meetings, SEPAC) a hand-typed PDF doesn't.
3. **A published PDF attendance/school calendar**, redirect-wrapped the same
   way lunch PDFs are (`/about-us/<year>-attendance-calendar` → a
   `resources.finalsite.net` PDF). Useful as a fallback when neither ICS
   shape exists, or as a cross-check. Read via Claude's native PDF document
   support (`{"type": "document", "source": {"type": "base64", ...}}`) —
   this is genuinely legible to Claude directly, don't bother with OCR/
   vision-on-images. **Prefer a Google/Finalsite ICS feed over building PDF
   extraction** if one turns out to exist too — check for both before
   committing to the PDF-parsing path, since the PDF is strictly less
   structured and won't self-update its URL next year (see "Track the page,
   not the link").
4. **A Google Doc** (`school_events_doc_url`, confirmed real: Cherry Hill
   West, embedded on an activities site Google Sites renders client-side, so
   a generic crawl never sees it linked). Regex-parsed by column position in
   the doc's own `txt` export, no model.

---

## Newsletters (Smore, or a bulletin-board equivalent)

**Fields:** `SmoreNewsletter` + `SmoreBlock` + `SchoolContentItem`, via
`services/content_extractor.py`'s extraction pipeline — shared across every
shape below through `SmoreNewsletter.source_type`.

**Shapes confirmed real, in order of how you'll actually find them:**

1. **A literal Smore issue link** (`source_type="smore"`, the original/
   default) — `app.smore.com/n/<code>`. **This is almost always the wrong
   thing to track long-term** — see "Track the page, not the link." Confirmed
   real: at least 7 of ~12 tracked schools in one representative 3-week span
   needed a brand-new URL at least once. Only use this directly when there's
   genuinely no stable page linking to the current issue (rare).
2. **A school's own "Newsletter Archive" page** (`source_type=
   "smore_archive"`) — lists every past issue itself, confirmed real two
   ways:
   - **Direct dated links** (Cooper Elementary): each issue's link text
     *is* its publish date (`"September 10, 2026"`). Pick the max parseable
     date.
   - **A link to a Smore AUTHOR profile instead** (Clara Barton Elementary):
     the archive page links only `smore.com/u/<username>` — a *second*,
     client-rendered Smore page (needs the scraper, `wait_for_selector=
     'a[href*="smore.com/n/"]'`) listing every issue that person has ever
     published, as thumbnail cards with **no date in the link text** — the
     date is a nearby `"Last edited <date>"` string a few DOM levels up
     from the link, not on the anchor itself.
   - **Neither of the above** (Haviland Avenue, a third real shape): an
     accordion page where each issue sits under its own `<h2>` tab titled
     with the date (`"September 25th"`, no year) and the link text is just
     a generic label (`"HAS Newsletter"`). No reliable date to parse from
     either the link or nearby text without inferring a year for a
     bare month/day — the safe fallback (last matching link in document
     order, since a real archive lists oldest-to-newest) already resolves
     this correctly; don't over-engineer year-inference here.
   - **A single always-current embed, no listing at all** (confirmed real:
     Rohrer Middle's own homepage, Jennings's `/our-school/newsletter` page)
     — the page just embeds `secure.smore.com/n/<code>?embed=1` directly and
     the school replaces that one embed in place each issue, no archive of
     past issues visible anywhere. Trivial for the resolver (exactly one
     `smore.com/n/` candidate on the page, picked automatically with no
     date logic needed) — point `smore_archive` straight at that page.
   - **Newest-first with the date as plain text *before* the link, not
     inside it** (confirmed real: Audubon HS's shared `/newsletters` page
     for multiple newsletters) — e.g. `March 2026 <a href=".../m8wrz">
     https://app.smore.com/n/m8wrz</a>`, then `Winter 2026` below it. The
     link text is just the bare URL. **This one is dangerous, not just
     unsupported**: the existing document-order fallback assumes
     oldest-first (true for Cooper, false here), so pointing `smore_archive`
     at a newest-first, no-date-signal page like this *silently resolves to
     a stale, older issue* instead of failing loudly. Needs a fourth
     date-detection strategy (a date in text immediately preceding the
     link) added to `_pick_current_issue_link` before wiring a page like
     this in — don't just point the URL at it and assume the existing
     three strategies are enough. Some pages instead mark the current one
     with an explicit label (`"CURRENT ISSUE OF THE COUNSELOR'S CORNER"`)
     — worth also recognizing that literal marker text, since it's an even
     more direct signal than a date once you're building this strategy.
   - **A single always-current `<iframe src=...>` embed, no `<a href>` at
     all** (confirmed real: Jennings Elementary's `/our-school/newsletter`
     page) — same trivial case as the plain-embed-page shape above, just
     rendered as an iframe instead of a link. `_pick_current_issue_link`
     checks both `a[href]` and `iframe[src]`.
   Every shape above routes through `services/smore_parser.py:
   discover_current_issue_url` once its detection strategy exists - no
   per-school code, just point the URL at whichever page you found. **But
   verify which shape you actually found before wiring it in** - the
   newest-first case above shows why assuming "found *a* listing page" is
   safe to wire in unread.

   **Migrating an already-tracked literal issue link to `smore_archive`
   changes that row's `url`.** The seed importer matches an existing
   `SmoreNewsletter` by exact URL - change the URL in the seed file and
   re-import, and it creates a **second**, duplicate row (with its own
   duplicate scan job) instead of updating the first, leaving the old
   literal-link row orphaned rather than replaced. Confirmed real, caught
   only by re-checking the DB after import rather than trusting the
   import summary's counts. After a migration like this, always verify
   there's exactly one `SmoreNewsletter` per school afterward and delete
   the orphaned old one (`DELETE /smore-newsletters/{id}`, which also
   removes its scan job) if a duplicate appears.
3. **A running bulletin-board/"virtual backpack" page** (`source_type=
   "virtual_backpack"`, confirmed real: Audubon, ~180 flyer/event links that
   only ever accumulate, never a single "current issue"). Each link is a
   Finalsite `/fs/resource-manager/view/<uuid>` wrapper redirecting to a
   PDF (or occasionally an external site — "Register Here" style). Dedup by
   the wrapper's own resource id (stable, no network call needed to check
   "have we seen this"), *then* resolve new ones. **Important: disable
   stale-year date correction for this source type** — `_correct_stale_year`
   assumes an old-looking date means reused flyer artwork in *this week's*
   Smore issue, which is true for a weekly newsletter but false for a
   permanent archive where most links genuinely are old. Getting this wrong
   fabricates false future events out of real historical flyers (confirmed:
   a 2024 flyer became a fake "October 2026" event on the first run before
   this was caught).

**Extraction detail regardless of shape:** most flyer links resolve to a PDF,
not an image — use `_document_extract` (Claude's native PDF support), not
`_vision_extract` (image-only). A link's title text alone often already
carries the date ("Movie Night Oct 2nd") — the PDF content only matters when
the title doesn't (bare "Flyer").

---

## Staff directory / who to contact

**Where:** `/contact-us` (Finalsite). Pagination (`?const_page=N`) *looks*
server-side but is entirely client-side — re-fetching page 2's URL directly
returns page 1's content. Must use `scraper_client`'s paginated fetch (one
held browser session, click `.fsNextPageLink`), not a plain per-page GET.

**Method:** `services/staff_roster.py`, `services/staff_roles.py`
(`classify_role` for the narrow contact-grid mapping, `classify_directory_category`
for the broader directory filter chips) — both keyword-map-based, generic.
Check whether the site has **titles** on each entry; if not (Voorhees-style,
just names + links), a school's own separate "Contact Us" page may need one
Haiku call to extract nurse/principal/etc. (`services/contact_page.py`)
instead — but only entries with a verbatim email+name on that page count,
never a guess.

---

## Absence / attendance reporting

**Fields:** `School.absence_method` (`phone`/`mailto`/`portal`/`other`) +
the corresponding phone/email/portal_url/instructions.

**Where:** search the school's own pages for "attendance," "absence," or
"report an absence." Shapes confirmed real: a dedicated phone line
(sometimes different from the main office number), a portal (Genesis,
ParentSquare — `parentsquare.com/schools/<id>/parent_absence_reporting`),
or a `mailto:` with prefilled body.

**Caution:** a bare main-office phone number is a *fallback guess*, not a
confirmed absence line, if no dedicated attendance page/instructions were
found — mark it as such rather than presenting it with the same confidence
as a verified dedicated line (confirmed real gap: Audubon's three schools
only had a Genesis-portal mention and main office numbers, no explicit
dedicated attendance phone confirmed on any of their pages).

**Sometimes this information genuinely isn't published anywhere on the
public site at all** — confirmed real: a thorough per-school pass across
all 11 Collingswood/Oaklyn/Woodlynne schools (Apptegy platform) found zero
dedicated attendance page, phone, or email on any of them; the only related
pages were board-policy legal text with no actionable contact info. Every
school links a Genesis portal, which is *plausibly* the real reporting
channel by analogy with other Genesis districts in this system, but that's
an inference, not a confirmed instruction on the page — don't write it in
as `"portal"` with confidence it doesn't have. Leaving `absence_method`
null and noting the gap honestly is correct here, not a research failure to
push harder on. (A handbook PDF linked from a "Documents" page might still
have it — worth a follow-up pass specifically through those PDFs if this
data is ever prioritized, since the nav-only crawl this guide describes
doesn't open documents.)

**`absence_method`/`absence_phone`/`absence_emails`/`absence_portal_name`/
`absence_portal_url`/`absence_instructions` are not settable through the
normal admin `PATCH /schools/{id}` endpoint** — `SchoolUpdate` doesn't
expose them, unlike the four bell-schedule time fields (`start_time` etc.),
which *are* PATCH-able. Absence fields can only be written by the
seed-file import path (`POST /admin/config/import`, `admin_config.py`),
which writes the model directly. Confirmed real: a PATCH with
`absence_phone` set in the request body silently drops that field with no
error - the response comes back with it still null. When filling in
absence data discovered this way, edit the seed file and re-import; don't
expect a plain PATCH to do it.

---

## Athletics (and band, if the district schedules it alongside sports)

**Fields:** `School.athletics_url`, feeding `services/arbiter.py` when it
resolves to a real ArbiterLive entity.

**Where:** the school's own `/athletics` page, usually linking an outbound
athletics site.

**Shapes confirmed real — `entity_id_from_athletics_url` recognizes all
three, but a *white-labeled* athletics site needs one extra hop to find
any of them:**

1. `arbiterlive.com/m/team/<id>`
2. `arbiterlive.com/Teams?entityId=<id>` (confirmed real: Cherry Hill East/
   West's own stored link was this shape, and the earlier version of this
   module didn't recognize it at all — their scan job was silently never
   created despite the URL "looking" valid. **Always re-verify an existing
   `athletics_url` actually resolves via `entity_id_from_athletics_url`
   before assuming it's covered**, don't just check that the field is
   non-null.)
3. `arbiterlive.com/School/Calendar/<id>` (confirmed real: Audubon HS,
   Eastern Regional)

**White-labeled ArbiterLive domains** (`<district>athletics.com`,
`<mascot>.arbiterwebsites.com`) are real ArbiterLive sites under a custom
domain, but `entity_id_from_athletics_url` can't extract an id from the
branded domain itself — fetch the branded site's own homepage and grep its
links for `arbiterlive.com`; it reliably links back to one of the three real
shapes above (its own "Calendar" or "Schedule" link).

**Band coverage:** confirmed real — when a school's real ArbiterLive entity
resolves, band events already come through the *same* combined calendar feed
as every sport (`"title":"Band - Coed Varsity"`, its own `sportId`). No
separate integration needed; this was purely a "does the entity id even
resolve" problem, not a "band isn't tracked" problem.

**"BigTeams" (`<school>.bigteams.com`) is also just ArbiterLive white-label
branding** — confirmed real: Haddon Township HS's `bigteams.com` site's own
homepage links `arbiterlive.com/School/Calendar/<id>` exactly like
`audubonathletics.com`/`easternvikings.arbiterwebsites.com` do. A search
engine describing a school's site as "on BigTeams" is *not* evidence it
needs a different integration - always fetch the branded site's own
homepage and check for a real `arbiterlive.com` link before concluding a
platform is unsupported (an earlier pass of this guide wrongly wrote
Haddon Township off as unsupported based on search snippets alone, without
actually fetching the site - a five-minute mistake, caught and fixed the
same session).

**`<id>.digitalsports.com`, seen alongside a BigTeams/Arbiter link for the
same school, is a genuinely separate, unconfirmed platform** - nothing in
this codebase reads it, and it wasn't needed once the Arbiter link resolved
Haddon Township's real schedule. Worth a real look only if a school's
*only* athletics link is a `digitalsports.com` one with no Arbiter link
findable anywhere on the branded site.

---

## PTA / PTO sites

Two platforms confirmed real so far, check for both (grep for `givebacks` and
`ptboard` per the crawl procedure above):

- **Givebacks** (`givebacks_shortname`) — already documented in CLAUDE.md,
  crawled multi-page since a PTA's Givebacks site has no fixed page naming.
- **PTBoard** (`<subdomain>.ptboard.com`, `source_type="ptboard"` on
  `SmoreNewsletter`) — confirmed real: Haviland Avenue Elementary
  (`haspta.ptboard.com`). Public, no login, server-rendered. The home page
  aggregates every active item (forms & payments, announcements, signups,
  campaigns, open registration) into `.content-summary-section` cards of
  `.feed-item` rows — parse generically across every section rather than
  writing one parser per section type, since they all share the row shape.
  **A search for other tracked schools on PTBoard (subdomain guessing +
  the site's own `/prf/findschool` search) turned up nothing beyond
  Haviland** as of this writing — don't assume it's worth guessing broadly
  for a new district without a specific link to follow, the hit rate was
  near zero.

---

## Deterministic parsers (no model call)

Marking periods, transportation, preschool locations/team, HS day rotation —
already thoroughly documented in CLAUDE.md's "Data sources and their
quirks." These are parsed with BeautifulSoup/pdfplumber specifically to
avoid a model mis-zipping which date belongs to which column; real gremlins
documented there (non-breaking spaces, weekday-prefixed dates, footnotes
glued onto dates) apply again on a new district's version of the same kind
of page. Check that section before assuming a new district's version needs
a novel approach — the parsing *pattern* usually transfers even when the
exact page layout doesn't.

**HS day rotation has two genuinely different real pathways — check both
before concluding a district needs the PDF one:**

1. **A district-published PDF** (`District.hs_rotation_url`,
   `services/hs_rotation.py`, `hs_rotation.scan`) — confirmed real: Cherry
   Hill's shared East/West "Day Schedule" PDF, parsed with pdfplumber word
   coordinates. This is the pathway to reach for when rotation days *aren't*
   already showing up any other way.
2. **Rotation days as regular calendar events**, already flowing in through
   the district's normal `ics_feeds` / `district_calendar.scan` — confirmed
   real: Eastern Regional's calendar publishes titles like `"Day 3 ( 3, 4,
   1, LL, 7, 8, 5)"` directly as event summaries on one of its calendar_ids
   (`school_today.py:_ROTATION_RE` reads these from `SchoolContentItem.title`
   the same way it reads any other calendar event - no separate scan or
   `hs_rotation_url` needed at all). **`District.hs_rotation_url` being
   null does NOT by itself mean rotation data is missing** - check for
   `SchoolContentItem` rows matching `^Day \d` before assuming a gap and
   going to build PDF-parsing support that isn't needed. (This tripped up
   an earlier pass of this exact guide - don't repeat it: verify against
   the database, not against which URL field happens to be null.)

---

## Known-unsupported platforms (don't rebuild these from scratch without checking first)

If a new district uses one of these, treat it as a genuinely new integration
decision, not a quick add. **Note the false alarm above: "BigTeams" is NOT
on this list** - it's ArbiterLive branding, already supported.

- **`<id>.digitalsports.com`** (athletics) — seen alongside a working
  Arbiter link for the same school (Haddon Township HS), never needed on
  its own so far. No code in this repo reads it.
- **MemberHub** (`<school>.memberhub.com`) — **not a separate platform to
  build**: those hostnames (and `.memberhub.store`) 301 to
  `<name>.givebacks.com`, so a MemberHub PTA link is a Givebacks site under
  its old name. Take the shortname from the redirect target and verify with
  `givebacks.resolve_org` (Thomas Edison -> `edison`; Haddonfield Central,
  Tatem -> `centralschoolpta`, `jftatempta`). Only Givebacks sites that
  actually carry content are worth a job: an org that resolves but has zero
  blocks just warns `givebacks_no_blocks` every run.
- **eBoard** (`<board>.<site>.eboard.com`, Haddonfield High/Middle PTAs) —
  302s to a login servlet on a host with an expired TLS cert; no public
  content. Same verdict as a login-walled Google Site: nothing to scan.
- **Padlet** (`padlet.com/<board>`) — a general-purpose board tool some
  small PTAs use in place of a dedicated platform, confirmed real (Stoy
  Elementary's PTA, Haddon Township). No code in this repo reads it - and
  since Padlet is a generic tool (not school-specific), a scanner for it
  would need to handle arbitrary board layouts, not one consistent shape
  the way Givebacks/PTBoard/Smore do.
- **A login-walled Google Site** (confirmed real: Van Sciver Elementary's
  PTA, `sites.google.com/view/van-sciver-pta` — redirects to a Google
  account login when fetched anonymously). Not a code gap, a genuine
  access gap: there is no public content to scan regardless of platform
  support. Don't spend time trying alternate fetch methods on a page like
  this; confirm it's actually login-gated (redirects to `accounts.google.
  com`) and move on.
- **ParentSquare Smart Sites (formerly SharpSchool)** — Evesham Township's
  platform, not Finalsite (page content is `#page-content-wrapper`;
  `/index.php?pageID=smartSiteFeed...` feeds). Not bot-protected: plain HTTP
  works, so no Playwright or residential proxy. `services/smart_sites.py` handles
  it: `school_info.scan` reads the footer's `aria-label`s (address, phone), and
  `staff_roster.scan` POSTs `/includes/ajax/load_stack_staff_directory.php`
  with the item id from the directory page's `getOnDemandDirectoryContent('<id>')`
  call (emails are base64 in `data-staff-email`). Both sniff the homepage for
  `smartsites.parentsquare.com` first, so no per-school flag. Only 2 of 10
  Evesham schools use the directory widget (DeMasi Middle 72 staff, Marlton
  Elementary 9). Beeler and Rice hand-type the list into the page body (no
  emails), parsed by `services/handtyped_directory.py` (role-first or
  name-first decided per page; a bare name under a pasted-table heading gets no
  title rather than a guessed one). Marlton Middle's legacy directory is empty,
  and Jaggard/Van Zant have per-role pages (/principal, /nurse-2) that
  `services/role_pages.py` reads as a fallback (a name counts only when placed
  like one: before an email, after a "Warmly," sign-off, or before its own
  job title); the preschools use a document viewer and report `no_staff_found`. `documents.scan`
  works on some. Calendars are not ICS: the district calendar is a PDF and each
  school page has a JSON API at `/api/calendars/<calID>/events?start_date=..&end_date=..`
  (`calID` in the page's `page_calendar?calID=` link) — no scanner reads it yet.
- **Lenape Regional (Finalsite)** - all five schools (Cherokee, Lenape, Seneca,
  Shawnee, Sequoia) are tracked. `/fs/calendar-manager/events.ics?calendar_ids[]=N`
  works though `calendars.json` 401s: 5 = days off, 27 = 4-day rotation
  ("Day 1 (AM: 1,2,3 - PM: 5,6,7)"), and one activities calendar per school
  (7 Lenape, 8 Shawnee, 9 Cherokee, 10 Seneca). Each school's `?feed_id=` link is
  just the union of 5 + 27 + its own, so the `calendar_ids` feeds cover them.
  Seneca/Shawnee share Cherokee/Lenape's bell schedule; Sequoia (and the TAP
  program at Seneca, not tracked) have their own on `/students/period-schedules`.
  Arbiter ids sit on the school site (Seneca `Teams?entityId=`; Shawnee's link is
  `/School/<id>`, which `entity_id_from_athletics_url` doesn't read - use
  `/School/Calendar/<id>`); Sequoia has no sports. The staff directory on every
  lrhsd.org school returns the same ~400 district-wide people.
- **A menu KeyError is the model dropping a "required" field**: `parse_menu_pdf`
  now skips a day with no description instead of failing the whole PDF.
- **A weekly student bulletin as a Google Doc** (`School.bulletin_doc_url`,
  `student_bulletin.scan`, `services/student_bulletin.py`) - Marlton Middle
  rewrites one doc in place. Track the *doc*, found from the school page. The
  doc holds events, club/fee/procedure notes, sports games and house-office
  contacts; sports lines and contacts are regex-parsed, the rest is one Claude
  call, skipped when the text+year hash is unchanged. Vanished rows are deleted,
  an empty parse never prunes.
- **Evesham/Lenape sports and band** need only `athletics_url` set to the
  school's ArbiterLive `/m/team/<id>` (Cherokee 4049, Lenape 12655, Marlton
  Middle 13916) - the existing `athletics_calendar.scan` job is auto-created and
  its calendar feed already includes band.
- **NJ DOE directory CSV** (`services/njdoe_directory.py`, `scripts/import_njdoe_contacts.py`): principal + anti-bullying specialist + homeless liaison per public school, downloaded by hand (the site is Incapsula-walled). Fills the who-to-contact gap for schools with no parseable roster; its emails are often the previous principal's, so one is kept only if it contains the person's surname.
- **A district calendar that is only a PDF** (`District.calendar_pdf_url`,
  `district_calendar_pdf.scan`, `services/district_calendar_pdf.py`) — Evesham
  publishes no ICS feed, just a one-page "2026-27 District Calendar" PDF linked
  from a page (`/244176_3`). Track the *page*; each run re-finds the PDF link
  (Smart Sites embeds it JSON-escaped in inline script) and reads the file with
  Claude's native PDF support. The scan skips the model call while the file's
  content hash is unchanged. Titles are composed in code from a model-chosen
  kind because `classify_day` lets "in-service"/"conference" beat a delay or
  early dismissal. A revised PDF replaces the old rows wholesale.
- **Lunch PDFs are kept for the current month and later** — an unbanded menu
  page lists one PDF per month, and only the latest used to be stored, which
  dropped the rest of the current month as soon as next month's appeared.
- **Merchantville (single PreK-8 school, Finalsite, Friday Parent Portal)**
  — `backend/seed/merchantville.json`. Finalsite calendar ids: 4 district, 9
  sports, 7 clubs (3 and 11 not wired; 9/7 are per-school via `school_slug`).
  The footer phone is plain text ("P: (856) 663-1091") with no `tel:` link, so
  `school_info._parse_location` falls back to the `.fsLocationPhone` text. The
  head of school is titled "Chief School Administrator", which `classify_role`
  maps to principal (exact title only). Bell start/end and absence method are not published, so left null rather than
  guessed. PTA is Facebook-only;
  no Smore/newsletter feed.
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
- **Maple Shade (Apptegy, `mapleshade.org`)** — 3 elementaries + HS,
  `backend/seed/maple_shade.json`, on Apptegy org ids 14327 (district) /
  14403–14406 (schools; read from each school's calendar page). The site
  answers plain HTTP with a JS challenge, so use the scraper to read it.
  Apptegy staff emails that are hidden come back as the literal `hidden`
  (`apptegy._real_email` drops them rather than storing it). The handbook is a
  Google Doc whose `export?format=txt` link gives the text. Gaps: the
  district calendar is a Drive PDF only; Wilkins and
  Steinhauer have no start/end times; no newsletters or athletics url; the HS
  uses EduRooms; `school_info.scan` can overwrite the HS address with a bare
  "Maple Shade, NJ 08052" (real: 180 Frederick Ave) — recheck after a scan.
  - **Lunch (Health-e Pro)**: `School.healthepro_location` = `org/site`
    (`2984/16222`...; site ids from `/api/organizations/2984/sites/list`),
    `healthepro_menu.scan`, `services/healthepro.py`. A public JSON API with
    no token; the per-day layout is `.../menus/{id}/year/{y}/month/{m}/
    date_overwrites`, and entrées are the recipes under a category ending
    "Entree". Preschool menus are skipped, and standing options are dropped
    with `fdmealplanner.day_descriptions`. The `/recipes/` endpoint has no days.

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
  - **SchoolCafé**: shortname `CAMDENCITYPS`, verified live.
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

- **Black Horse Pike Regional (Finalsite) + its sending districts** — Runnemede
  (above), Bellmawr, Gloucester Township. `backend/seed/{black_horse_pike,bellmawr,
  gloucester_township}.json`. BHPRSD runs Highland (Blackwood), Timber Creek (Erial)
  and Triton (Runnemede); `towns` is Bellmawr, Gloucester Township, Runnemede.
  - **BHPRSD**: one Finalsite site (`www.bhprsd.org`) plus a subdomain per high
    school (`hhs`/`tchs`/`ths`). Calendar ids work on every host and are shared:
    1 Triton, 3 Timber Creek, 4 Highland, 10 Highland Athletics, 13 Triton
    Activities (6 Timber Creek and 8 Triton Athletics, 11 counseling and 12 weekends
    were empty in October). Each is attached with `school_slug`. Lunch is one
    district PDF per month plus a breakfast PDF at `/our-district/food-services/monthly-menu`
    (no SchoolCafé match under any Nutri-Serve shortname tried). **Athletics are
    on GoBound (`gobound.com/nj/schools/...`), not ArbiterLive** — nothing reads it,
    so `athletics_url` is null; the ICS athletics calendars cover Highland only.
    Bell schedules are linked PDFs/images, so times are null.
  - **Bellmawr and Gloucester Township are Apptegy**, not Finalsite, though a plain
    GET returns Finalsite's "Client Challenge" interstitial — go straight to the
    scraper. A school's Apptegy org id is the most common `cmsv2-assets.apptegy.net/
    uploads/<id>/` in its rendered home page (`/o/<code>`); the district's is the
    same on `/`. Verify with `apptegy.fetch_events`. Bellmawr district 10774; GT 23780
    (23874 also answers, with 647 unrelated events — not the district).
  - **Bellmawr lunch**: SchoolCafé `BellmawrPublicsdNutriServemetz` (found on the
    menu page's links; `GetISDByShortName` confirms). Hours are on the district
    footer. **GT lunch** is Health-e Pro, org 2546 (all 11 sites, ids from
    `/api/organizations/2546/sites/list`; the district's menu page itself is empty,
    so it was found by the owner). The Preschool Program (org 25533) is not tracked.
  - **Gaps**: no absence method, hours (GT, BHPRSD), logos for two Bellmawr schools,
    newsletters or PTAs anywhere; Bellmawr's EC Center shares Bellmawr Park's address
    and its phone is unverified.
