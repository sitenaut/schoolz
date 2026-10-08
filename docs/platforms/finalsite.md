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
