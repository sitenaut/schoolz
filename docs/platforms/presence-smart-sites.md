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
  - **ArbiterLive has a school search**:
    `https://www.arbiterlive.com/School/Search?searchString=<name>` lists
    `/School/<id>` links. Delran's own "Sports Schedule" page only redirects to
    the Arbiter home page, so the ids (and the two middle schools') came from
    there; `Teams?entityId=<id>` is the form the scan reads.
  - **Bell schedules as pictures** (Delran High: three PNGs; Delran Middle:
    scanned PDFs still dated 2024-25) were read by eye and typed in.
  - **Checked and not wired**: Delran's MS/HS PTA resolves on Givebacks
    (via its MemberHub link) but has zero blocks; the elementary PTO's site was
    last posted in 2021. Delran's calendar PDF has no marking periods.
    Neither district's transportation page matches a parser (a phone, staff
    and bus rules on a Smart Sites page; a phone and "see the parent portal"
    on Presence).
  - **Gaps**: transportation; Delran marking periods; no nurse or titles for
    Delran High; no absence method for Eleanor Rush or the preschool; the
    preschool's hours (four programs, one set of flat times) and lunch; Rush's
    newsletter page and the preschool's bulletin page are empty; Delran's
    district newsletter is a Presence documents widget nothing scans.
