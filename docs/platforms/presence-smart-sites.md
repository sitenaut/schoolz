# Presence and ParentSquare Smart Sites (ex-SharpSchool)

Evesham, Sterling, Somerdale Park (Presence), Cinnaminson (Smart Sites), Delran (Presence). Both vendors answer plain HTTP but hang headless Playwright in places: try httpx first.

Per-district notes moved out of `docs/ONBOARDING_CRAWL_GUIDE.md` so a crawler loads only the platform it is looking at. Same rules: when you confirm a new shape, add it here in the same PR.

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

- **Cinnaminson (ParentSquare Smart Sites) and Delran (Presence)** — both K-12
  with no sending or receiving partners. Seeds
  `backend/seed/{cinnaminson,delran}.json`.
  - **A Smart Sites calendar may be a Google Calendar underneath.** The
    `/api/calendars/<calID>/events` JSON says so itself: `feed_source: "google"`
    and a `calIDref=<id>@group.calendar.google.com` in each event's `link`. That
    id's public iCal feed works with no code, so no JSON scanner was needed.
    A school's `calID` only answers on that school's own host, and its page
    mixes in the district calendar, so read the distinct `calIDref`s.
  - **Nutrislice** (`cinnaminson.nutrislice.com`): school slugs come from
    `https://<district>.api.nutrislice.com/menu/api/schools/?format=json`.
    The preschool has no site of its own (New Albany carries a "Pre-K
    Breakfast" type, not read).
  - **Smart Sites directory widget with no real titles**: every Cinnaminson
    row is titled "Teacher", so no contact resolves from it. Nurses come from
    each school's nurse page, where the name is the line carrying nursing
    credentials ("..., RN, BSN, CSN" — `role_pages._credentialed_nurse`);
    principals from the NJ DOE CSV (`scripts/import_njdoe_contacts.py`, a
    one-off per environment). The footer phone prints "+1", stripped.
  - **Presence calendars**: `https://<host>/ICalendarHandler?calendarId=<id>`,
    where the id is the `parentId.<n>=` value in the home page's event links
    (not `contextId` or `pageId`, which answer with zero events). Delran's
    district calendar is the union of its four school calendars under
    different UIDs, so only the school feeds are wired; closures therefore
    arrive once per school, school-scoped.
  - **Staff lists as published Google Sheets** (Delran): each school's "Staff
    Listing" page is an iframe of `docs.google.com/spreadsheets/d/e/<key>/pubhtml`.
    `pub?gid=0&single=true&output=csv` exports it (`output=xlsx` 400s on some).
    The high school's sheet has an empty Title column.
  - **Presence header address**: Delran's template has no footer box; address
    and phone are `ul.address` items told apart by their icon.
  - **ArbiterLive has a school search** (see the guide's athletics section):
    `https://www.arbiterlive.com/m/search?searchString=<name>&state=NJ` lists
    `/m/team/<id>` links (the older `/School/Search` now returns nothing).
    Delran's own "Sports Schedule" page only redirects to
    the Arbiter home page, so the ids (and the two middle schools') came from
    there; `Teams?entityId=<id>` is the form the scan reads.
  - **Bell schedules as pictures** (Delran High: three PNGs; Delran Middle:
    scanned PDFs still dated 2024-25) were read by eye and typed in.
  - **Checked and not wired**: Delran's MS/HS PTA resolves on Givebacks
    (via its MemberHub link) but has zero blocks; the elementary PTO's site was
    last posted in 2021. Delran's calendar PDF has no marking periods.
    Both transportation pages are read by `transportation.parse_department_page`:
    Cinnaminson's `/transportation-home` (the bare `/transportation` page is
    empty) puts each number a few lines under a staff title, and Delran's
    Presence page has no `main`, so its content is `.pageContent`, with each
    value on the line under its label (Phone, Fax, Hours).
  - **Gaps**: Delran marking periods; no nurse or titles for
    Delran High; no absence method for Eleanor Rush or the preschool; the
    preschool's hours (four programs, one set of flat times) and lunch; Rush's
    newsletter page and the preschool's bulletin page are empty; Delran's
    district newsletter is a Presence documents widget nothing scans.

- **Gateway Regional / Woodbury Heights** — `backend/seed/gateway_regional.json`,
  `woodbury_heights.json`. Gateway is Presence (`/district/staff_directory`,
  not `/staff_directory`; the "More..." button is only UI, the web service
  returns every email; its Settings call also lists system groups Parents,
  Students, Registered Users, Pending_Delete_Users, which the scan skips), and
  its bell-schedule and calendar pages are PDFs served at a normal page URL.
  Woodbury Heights is Smart Sites: `/263941_2`-style nav items are redirect
  stubs to a Google embed, Drive file or PDF; its staff directory is a
  published Google Sheet CSV. Both lunches are Nutrislice tenant `grsd`
  (Gateway's), which also lists National Park, Parkview (slug
  `parkside-elementary-school`: the slug differs from the site's name, probably set
  when the site was created; it is what the API and Westville's own site use, so
  don't "correct" it, the `parkview-` form 404s) and Woodbury Heights, so match by name.
  Gateway's own events are on its Arbiter calendar (`/School/Calendar/8327`), which
  the athletics scan reads: `/m/game/<id>` items are games (hidden by default),
  `/m/event/<id>` items are events, shown (`source=arbiter_events`) only for a school with
  `arbiter_events_calendar` set (Gateway, Haddon Heights High, HTHS, Audubon); with `arbiter_events_district_wide` too (Audubon, whose one district calendar sits on its high school's Arbiter account) they are stored district-scoped. A sweep of all 44 tracked Arbiter ids found events on 12;
  at most they are team business (open gyms, tryouts, team dinners), which stays hidden
  with the games. Event titles carry HTML entities.
  The calendarmonth feed has no status, so cancellations come from the school calendar
  page's own feed (`POST /School/GetEventsByEntity/` after a GET of `/School/Calendar/<id>`,
  which sets the entity in the session): titles carry a badge, `Canceled`, `Postponed` or
  `Rainout`, and the scan prefixes the title ("CANCELED - ..."). That feed also lists
  practices, which the scan does not import.
  Gateway's district calendar is a one-page PDF at a stable page URL (`calendar_pdf_url`), a
  two-column year grid (July-December left, January-June right) whose entry lists sit beside
  each mini-month. `district_calendar_pdf.layout_text_by_month` assigns each entry to its month
  by position before the model classifies it; read whole, the model moved right-column entries
  a month early.

## Monroe Township (Gloucester County)

- Nine Google calendars come from `/api/calendars/<calID>/events` (`calIDref`s on each event link): district, BOE, one per school. Non-`@group` ids are plain emails (`mtpsnews@gmail.com`).
- The directory widget returns a **table** (`tr[data-staff-name]`, Name and sometimes Title columns), one `getOnDemandDirectoryContent` item per grade/department; `smart_sites.parse_directory` reads both this and the card layout. Nav labels vary ("Faculty & Staff", "Oak Knoll Staff Directory"); `find_directory_links` matches both.
- "Loading document viewer..." pages (handbooks, Kids Choice, specials) hold the file URL as JSON-escaped text (`files.smartsites.parentsquare.com\/<n>\/x.pdf`); a plain href grep misses it.
- Athletics pages redirect to GoBound; ArbiterLive ids come from `/m/search?searchString=<town>&state=NJ` (other states have same-name schools).


## Tabernacle (found onboarding)

- A district can have **no school subsites at all**: both schools' `website_url` is the district site, whose footer is one building's. `school_info.scan` therefore only fills blanks when another school shares the site (it once gave the elementary the middle school's address).
- **Legacy directory** (`/directory`, a `/<page>_2` slug): server-rendered `li.ss-directory-ppl-list__card` cards (first `<br>` last name, `div.dir_title` role like "Principal - TES", empty `data-staff-email`), paged by plain `?offset=24&ppl=2` links. There is no `getOnDemandDirectoryContent` widget; `smart_sites.fetch_roster` reads this layout and follows the offset links.
- Document-list pages (sports schedules, HSA newsletters, district calendar) link `files.smartsites.parentsquare.com` PDFs directly.
- The home-page calendar widget's `/api/calendars/<id>/events` gives the Google `calIDref`; its public `basic.ics` is the feed.

## Edgewater Park (found onboarding)

- **Schools as pages of one district host** (`edgewaterparksd.org/mildred-magowan-elementary-school`): the site-relative AJAX endpoints (`/includes/ajax/load_stack_staff_directory.php`, `/api/calendars/<id>/events`) answer only at the host root (under the page they 404), and every page's footer is the district office. `smart_sites.fetch_roster` posts to the origin, and `discover_school_info` flags a sub-page as `shared_footer` so `school_info.scan` only fills blanks.
- A contacts page can hold both a hand-typed role list (name, title, `mailto:`) and a `getOnDemandDirectoryContent` widget whose titles are a group label ("MES Teachers"); `fetch_roster` reads only the widget, and the contact-page fallback found the nurse but not the principal (NJ DOE CSV fills that).
- `staff_directory_url` is for a directory published as a document (PDF, Google Sheet or Slides); setting it to a contacts page makes the roster scan parse that HTML as a PDF and fail.
- Everything else is Google Drive `file/d/<id>/view` links (menus, the district calendar PDF, forms). `district_calendar_pdf._drive_calendar_link` reads only text before the anchor, so a link whose own text is "District Calendar" is missed.

## Palmyra and Riverside (found onboarding)

- **Every Smart Sites calendar has a public ICS**, Google-backed or not: the calendar app's Subscribe button (`/page/subscribe?calendar_id=<id>`) prints `https://<host>/sndreq/generateCalendarICS.php?calendar_id=<id>`. The API's `feed_source` says `ics` (imported from ParentSquare, no `calIDref`) or `ss` (native). The generated file's UIDs are PHP `uniqid()` values minted at each rebuild (cached for hours), so `district_calendar` keys that URL's events on title and start.
- `parentsquare.com/feeds/<id>` returns 401 anonymously; the same post is public at `<host>/index.php?pageID=smartSiteFeed&psqFeed=true&articleID=<id>`.
- A nav item can redirect straight to a Google Sheet whose default export is the first tab (Palmyra's is a 2024 draft): pick the tab's gid.
- Riverside is the Tabernacle/Edgewater shape (school pages on one host), but all three buildings share one campus address, so the district footer is right for each. Its directory widget returns the `.staff-item` carousel (no emails). A district calendar that unions school calendars can hide one school's missing closures: check each feed.
- A Smart Sites slug can 302 straight to an `app.smore.com/n/<code>` issue (Riverside's `/ramfam-review`), so tracking that page is tracking a literal issue.

## West Deptford (found onboarding)

- A school's `/staff_directory` can be a plain nav page with the component at `/staff_directory/searchable_directory` (now in `_PRESENCE_PATHS`); the district's is at `/district_info/staff_directory`.
- The district calendar PDF can be served straight from a dated page URL (`/calendar/2026_2027_District_calendar`); `/calendar` itself links that page, not a `.pdf`.
- Bell schedules can be page URLs that redirect to CDN JPGs.

