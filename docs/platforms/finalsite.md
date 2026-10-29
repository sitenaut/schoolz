# Finalsite

Lenape Regional, Merchantville, Pennsauken, Black Horse Pike Regional (which also covers Bellmawr and Gloucester Township, both Apptegy: see apptegy.md). Most common platform so far; the main crawl guide already covers its calendar/lunch/roster patterns.

Per-district notes moved out of `docs/ONBOARDING_CRAWL_GUIDE.md` so a crawler loads only the platform it is looking at. Same rules: when you confirm a new shape, add it here in the same PR.

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

- **Merchantville (single PreK-8 school, Finalsite, Friday Parent Portal)**
  — `backend/seed/merchantville.json`. Finalsite calendar ids: 4 district, 9
  sports, 7 clubs (3 and 11 not wired; 9/7 are per-school via `school_slug`).
  The footer phone is plain text ("P: (856) 663-1091") with no `tel:` link, so
  `school_info._parse_location` falls back to the `.fsLocationPhone` text. The
  head of school is titled "Chief School Administrator", which `classify_role`
  maps to principal (exact title only). Bell start/end are not published, so left null rather than
  guessed. Absence reporting *is* published, but only in an "Attendance Info for
  Families" Google Doc linked from `/support-resources` (its `/export?format=txt`
  works anonymously): call the main office, ext. 510, before 8:45 AM. A nav-only
  crawl misses it. PTA is Facebook-only;
  no Smore/newsletter feed.

- **Pennsauken (Finalsite, one subdomain per school)** — `backend/seed/pennsauken.json`.
  - **Calendar ids are in the page HTML**: each `.fsCalendar` on `/calendars` carries
    `data-calendar-ids="N"` under a titled tab, so no clipboard intercept is needed
    (`calendars.json` 401s). 2 District, 9 PHS, 3 Burling, 8 Phifer, 10 Intermediate,
    11 Roosevelt, 13 Baldwin, 4 Carson, 5 Delair, 6 Fine, 7 Franklin; skip 1 (sample),
    12 Purchasing, 14 Weekends. Ids work on every host. Every school feed re-posts the
    district Board Meetings under the same UIDs.
  - **Feed 2 has no closures.** Holidays/closures/early dismissals are only in the
    year-calendar PDF on `/calendars`, so `calendar_pdf_url` tracks that page. Its link
    is a resource-manager wrapper (`<a data-file-name="...Calendar...pdf"
    href="/fs/resource-manager/view/<uuid>">`) with no `.pdf` in the href, and a
    school's direct-linked `CarsonCalendarforSept2026.pdf` sits further down;
    `district_calendar_pdf.find_pdf_link` checks resource-manager anchors first.
  - **Resource lists are often `<button data-resource-uuid>` with no href** (Spear
    Point pages); `/fs/resource-manager/view/<uuid>` on the school host redirects to the
    file. The nearby label belongs to the *previous* item, so identify a uuid by the
    filename it redirects to. Many PDFs are scanned images with no text layer.
  - **Lunch is Nutrislice** (`pennsauken/<slug>`, all but Burling). Every food has an
    empty `food_category`; the day's main item is listed first, so
    `nutrislice.entrees` takes the first food when nothing is categorized.
  - **Bell times**: `/families/school-bell-schedules` (mirrored on every host) has
    flat times for some schools and links each school's own PDF; others post the PDF
    only on the principal's "Spear Point" page (slug varies: `/meet-the-principal/spearpoint`,
    `/meet-the-principals/the-spear-point-principals-resources`). Because every host
    lists every school's PDF, `documents.scan` keeps a bell schedule only when its
    *file name* names this school (short name, first word or initials, e.g. `PHS`;
    district-name words don't count) and drops the ones naming a sibling. Carson's
    PDFs are unnamed resource links, so Carson gets none.
  - **Footer phone** `tel:` links carry a hidden "Phone: " label; `school_info` keeps
    only the number.
  - **Athletics**: ArbiterLive `Teams?entityId=17834` is the high school (and also
    carries some middle-school teams); Phifer Middle is `/m/team/10545` (the owner
    supplied it). `pennsaukenindiansathletics.com` is VNN/PlayOn, not an Arbiter
    white-label.
  - **Staff**: per-school `/directory` (client-paginated, departments, no titles;
    every school has "FILLER STAFF <code>" placeholders, which `_parse_page` drops).
    Baldwin's 83 span two pages; its first paginated run came back empty after 3
    minutes and the re-run got 69, so treat one empty run as transient.
    No `<img>` in the school headers, only hero photos; every school uses the district logo.

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
    ArbiterLive** (`/m/team/<id>`: Highland 10054, Timber Creek 23438, Triton
    23768; the owner supplied the ids, the schools' own pages link GoBound). The
    schools' athletics ICS calendars repeat the same games under different titles,
    so they are left out of the seed; removing a feed does not delete its old rows.
    **Bell schedules** are Google Drive PDFs (Highland, Triton: regular, half-day,
    2-hour delay, assemblies; `drive.google.com/uc?export=download&id=` serves the
    bytes) and, for Timber Creek, a single regular-schedule PNG (Finalsite's
    `f_auto` returns a PNG even for a `.pdf` URL). Highland and Triton share the
    7:20-2:01 day and the same half-day (ends 11:45); only lunch/activity time
    differs (Tartan vs Mustang vs Charger Time).
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

- **National Park** — `backend/seed/national_park.json`. Calendar id 1 is the
  real one (`/calendar-f2` widget `data-calendar-ids`; 2 is the sample, 3 empty).
  Hours and absence method exist only in a Family Handbook Google Doc
  (`/export?format=txt` works anonymously). Staff list paginates `?const_page=1..3`.
  Lunch is the shared `grsd` Nutrislice tenant.

- **Washington Township SD (Gloucester)** — `backend/seed/washington_township_gloucester.json`. Multi-site Finalsite:
  `www.wtps.org/` serves the WTHS home page and `/calendar`, `/staff-directory-link` serve Bells, so use `www/our-district/...`
  for district facts and each school's subdomain for school facts. Calendars are Google Sync feeds, one id per school plus
  district id 3, which is a *union* of every school's events (418) and also carries the closures: the feed carries
  `skip_title_prefixes` (school names) so the school feeds keep their own events instead of losing them to the district-UID
  subtraction. Elementary page slugs carry per-school `-clone` suffixes; copy errors carry over (Hurffville's admin page shows Birches'
  phone), so trust the footer. Bell times are one district PDF (rows per building group: BE-TJ-WH, BI-HU-WW, MS, HS) behind
  `/our-district/district-bell-schedule`. The calendar PDF is a resource-manager nav link; `calendar_pdf_url` points at that
  wrapper directly (the directory page did not yield it). Athletics: WTHS is on GoBound but the owner supplied its ArbiterLive team id.
  Lunch menus mix resource-manager PDFs (past months) and fixed-name PNGs (current month); the PNG links are classified by link text, since the filename says nothing.

- **Burlington Township (older calendar module):** `/fs/calendar-manager/events.ics` returns an empty VCALENDAR for every id, and the "subscribe" button does nothing. The RSS button opens a popup at `/cf_calendar/cms_calendar_feeds.cfm?element_id=N&calendar_ids=<data-calendar-ids>` whose "Add to Default Calendar App" links are the real feeds, `webcal://<host>/calendar/calendar_<id>.ics` (plus one `cf_calendar/feed.cfm?type=ical&feedID=` for all). Find it by clicking the RSS button in Playwright and watching for a popup, not the clipboard. Plain curl to this host has also been served other districts' pages: check the page title.

- **Southampton Township:** calendar ids 2 ("Events") and 3 ("Master Calendar (Public)") return the same 407 events under different UIDs; wire only one. `calendars.json` 401s, so ids came from `data-calendar-ids`. School subsites (`schoolN.stsdwarriors.org`) carry almost nothing; the bell schedule is one district page (`/schoolssxz/bell-schedules`, each table rendered twice). The staff directory is one district list at `/district/staff-directory` (names and emails, no titles or locations), not a path the scan tries.
- **Eastampton and Lumberton (older calendar module, as Burlington Township):** the `cms_calendar_feeds.cfm?element_id=N&calendar_ids=<ids>` popup answers a plain GET, so no Playwright is needed. Ids are large (Eastampton 351, Lumberton 358-361 and 365), read from `data-calendar-ids` or `data-calendar-component--controls-calendar-ids-value` on each site's `/calendar`. `/calendar/calendar_<id>.ics` 302s to `/data/calendar/icalcache/` and serves a rolling window of about three months, not the year. Lumberton's district feed repeats each school's events with the building as a title prefix ("BRS Lego Club") under new UIDs, and each school feed repeats the district's closures under new UIDs too: the district feed takes `skip_title_prefixes`, and `district_calendar_scan` drops a school-feed event with the same day and title as a district one. Eastampton's id 349 is a "DEV test" calendar of 242 "Event Title" rows.
- **Lumberton** keeps the bell schedules and absence rules for all three schools in one District Handbook Google Doc (`export?format=html` keeps the real tables), and its staff directory is one district list at `/for-families/home` (163 people, titles and building per card), a path `staff_roster` doesn't try, so each school sets `staff_directory_url`.

## Lawnside and Waterford (found onboarding)

- Finalsite appends a hidden `<span class="fsStyleSROnly">(opens in new window)</span>` to every link that opens a new tab, so a link's full text is "September(opens in new window)". Compare link text through `smore_parser._visible_text` (or drop `fsStyleSROnly` spans) before matching it.
- A district staff directory served on every school host, listing all staff with a Location column (Waterford, `<school>.wtsd.org/staff-directory`), is split per school by that column: each school keeps only its own.
- A transportation department can be one page (Waterford's `/our-district/transportation`): `transportation.scan` reads Cherry Hill's subpage tree only when the main page links `late-bus-information`, and any other page with `parse_department_page`.
- A scanned calendar PDF can mark closures only by colour with a key ("red = School Closed"); see the Waterford entry in `docs/DATA_GAPS.md` for how far the image prompt gets.

## Chesterfield, Springfield and Mansfield (found onboarding)

- Older calendar module: `data-calendar-ids` can be unquoted and comma-separated (`data-calendar-ids=351,350`); `calendar_<id>.ics` windows vary from ~2.5 to ~7 months, so a year PDF may be needed for later closures.
- A calendar id can be a lunch menu (Springfield's 352: daily entrées, "HALF DAY - Hot Dog"): never wire it as an ics feed.
- A specials rotation can be "Cycle Day N" (Chesterfield); `district_calendar` stores it as "Day N".
- The home page's calendar can be a Drive link labelled only by its own text (`<a>2026-2027 School Calendar</a>`), which `_drive_calendar_link` now reads.
- A Finalsite district can put each school on a Google Site (Mansfield): no `.fsLocationAddress`, and the district's constituent directory is out of the roster scan's reach.

