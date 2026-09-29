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
   All three route through `services/smore_parser.py:discover_current_issue_url`,
   which tries direct links first, then the author-profile hop, then falls
   back to document order — no per-school code needed, just point the URL at
   whichever page you found and let it resolve.
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

**Not every school is on ArbiterLive at all** — confirmed real: Haddon
Township HS is on a completely different platform (`bigteams.com` /
`<id>.digitalsports.com`), which nothing in this codebase supports yet. Say
so plainly rather than reporting a gap as "still investigating" — a
different-platform school needs a new integration, not a better search.

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

---

## Known-unsupported platforms (don't rebuild these from scratch without checking first)

If a new district uses one of these, treat it as a genuinely new integration
decision, not a quick add:

- **BigTeams / `<id>.digitalsports.com`** (athletics) — confirmed real,
  Haddon Township HS. No code in this repo reads it.
