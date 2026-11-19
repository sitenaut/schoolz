# Apptegy

Maple Shade. Bellmawr and Gloucester Township are also Apptegy: their notes sit inside the Black Horse Pike entry in finalsite.md.

Per-district notes moved out of `docs/ONBOARDING_CRAWL_GUIDE.md` so a crawler loads only the platform it is looking at. Same rules: when you confirm a new shape, add it here in the same PR.

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

- **Clayton (Gloucester)** — `backend/seed/clayton.json`. Plain GET returns a Finalsite-style "Client Challenge", so use the scraper. School orgs return empty directories; the district org holds the whole roster (department chips ES/MS/HS/ECC). Documents are `aptg.co/<code>` / `5il.co/<code>` short links to expiring signed S3 URLs: track the page, never the target. The athletics entity id came from the VNN/PlayOn athletics site's partner list ("Arbiter API" thirdPartyId), then verified at `arbiterlive.com/School/<id>`.
  Lunch menus are PDFs in `<iframe src="https://aptg.co/<code>">` on per-level pages (`/o/cpsd/page/*-menus`) that only the nav JSON of the food-service page links to. `lunch_menu._discover_embedded_menus` follows those links, downloads each embed, and classifies it by the PDF's own heading ("HS/MS Lunch Menu October 2026", which serves both the high and middle school); the short link itself is stored and re-fetched. SchoolCafe resolves for this district but lists no schools, so `schoolcafe_shortname` is null.

- **Wood-Ridge (Apptegy, `wood-ridgeschools.org`)** — Doyle, Intermediate, Jr/Sr High, `backend/seed/wood_ridge.json`. Plain GET shows Finalsite's "Client Challenge"; the tell is `cmsv2-assets.apptegy.net/uploads/<id>` and `/o/<code>` paths (`wrsd`, `cede`, `wris`, `wrhs` — read the codes from the district nav, don't guess initials). Org ids 22814 district, 23145/23146/23147 schools. Opposite of Clayton: the school orgs hold the rosters (87/33/72) and the district org holds 9. School orgs carry district items (closures, half days) in their own event feeds, so seed the district feed plus each school's. Nav and body links (handbook, calendar PDF, Smore) live in escaped JSON, not anchors; `aptg.co`/`5il.co` are expiring short links. Athletics is DigitalSports (see the data-sources skill). Lunch is Health-e Pro org 3927 (`3927/<site>`; site ids from `/api/organizations/3927/sites/list`).

## Willingboro (found onboarding)

- Page bodies are client-rendered; `https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/<org>/cms/pages/<slug>?locale=en` returns them without auth. Some pages (start times) are only an image.
- A district can move domains and leave the NJ DOE and staff emails on the old one (`wboe.net`); check the live domain first.
- The district food page can link `<tenant>.schooldish.com`, which redirects to `<tenant>.myschoolplate.com` (supported). A location with no menu published for a month answers a null `locationRecipesMap`; Willingboro's elementary menus are PDFs on the location pages (see the `data-sources` skill).
- The district events org already carries school-prefixed events; check dedup before wiring school orgs too.


## Shamong / Woodland (found onboarding)

- **A district can live inside another district's Apptegy tenant** (Woodland's single org 26750 sits in Shamong's: section names `*-ces-shamongtownshipnj`, Shamong's org ids in the embedded org list). Seed only the org ids the site's own `/o/<alias>` and `api/v4/o/<id>` URLs use.
- **School orgs can be empty while the district org holds every school's staff**, with a department chip per building (Shamong: `IMS`/`IMMS`; Clayton: `ES`/`MS`/`HS`). `staff_roster.scan` falls back to the district org (the district's apptegy `ics_feeds` entry with no `school_slug`) and keeps people whose department is the school's `/o/<alias>` upper-cased, or its type code when no sibling shares the type.
- **The full calendar can sit on one school org** (Shamong: 2026-27 is on the middle school's org 6548; the district org and the elementary org are nearly empty). Count each org's events for the current year before choosing feeds.
- Page JSON (`.../cms/pages/<slug>`) holds links with JSON-escaped quotes, and a Drive calendar link can be labelled only "2026-2027", which `district_calendar_pdf.find_pdf_link` doesn't pick up; Shamong's `calendar_pdf_url` is the Drive file's `uc?export=download&id=` URL, so it needs updating each year.
- `scores_schedules` (`.../cms/scores_schedules`) can be a middle school's only athletics schedule (Shamong); nothing reads it.
- `cms/documents` and `cms/articles` 404; Drive folders list their files in plain HTML at `drive.google.com/embeddedfolderview?id=<id>`.

## Westampton (found onboarding)

- **District and school orgs can each hold a full copy of the same event list under different event ids** (Westampton 4387/4388/4390, 49 events each). Seed the district org only, or every item appears three times; school orgs still go in `apptegy_org_id` for their rosters.
- The current calendar PDF can be linked only from the header as an `aptg.co` short link to an unsigned thrillshare asset, while the "Dismissal Times/Calendar" page still lists a prior year. The feed carries the same closures, so `calendar_pdf_url` stays null.
- A plain GET gets a "Client Challenge" page; page bodies come from `thrillshare-cmsv2.services.thrillshare.com/api/v4/o/<org>/cms/pages/<slug>` without auth.

## Glassboro (found onboarding)

- A plain GET can return a Finalsite-style "Client Challenge" even though the site is Apptegy (as at Bellmawr, Clayton, Wood-Ridge); org ids are in the home page's serialized org list (`'Glassboro High School','/o/ghs','ghs','www.gpsd.us/o/ghs',26997`).
- A district can prefix every event title with a building code ("GHS:", "TEBMS:"); nothing scopes by it yet, so a building's status items land district-wide.
- Some footers keep the address and phone as free text in `.footer-columns p.textfield` with no `a.tel-link`, so `discover_school_info` finds only the logo.

## Northern Burlington (found onboarding)

- The calendar and bell-schedule PDFs can be linked only from the site header's nav data (5il.co short links); the school sites' headers point at different bell PDFs than the district's.
- A district's Apptegy events can stop months before the school year ends; check the last event date before relying on the feed for closures.

## New Hanover (found onboarding)

- **An all-day event's `end_at` is its last day** ("2026-11-27T00:00" for Thanksgiving Nov 26-27; a one-day closure ends on its start), unlike ICS. `apptegy.fetch_events` adds a day so `end_date` means the day after, as everywhere else; before that, every multi-day Apptegy closure's last day read as a school day.
- The rendered home page carries the whole nav tree as JSON (`"menu":[...]`), the quickest list of page slugs; `/documents/<folder>/<id>` pages list unsigned `files-backend.assets.thrillshare.com` PDF URLs.


## Township of Franklin and Clearview (found onboarding)

- Each school org can carry a near-full copy of the district's union feed under different event ids (the Westampton shape) and add a few events of its own: wire the district org with `school_title_prefixes`, plus only the school orgs that add events after dedup.
- Every org of a district can also return one facility/activities section (Clearview: 1,758 practices, rentals and games under "Activities and Athletics" beside a 22-event "District Calendar"). The API ignores `slug=`, `custom_section_id=` and `section_id=`; each event's `custom_section_name` is read into `section`, and the feed's `skip_sections` drops it.
- A district roster's department chips can be full building names (Township of Franklin), a third shape after alias codes (Shamong) and type codes (Clayton); or building membership can live only in `meta.filters`/`filter_ids` with a uniform department (Clearview), which nothing reads yet.
- Lunch menus can sit in a documents folder whose file links render only client-side (`cms/documents` 404s).
- A calendar PDF short link can resolve to a file named for the prior year whose content is the current year.

- **Mercer County (East Windsor, Hopewell Valley, West Windsor-Plainsboro)** — A school org's copy of district events can sit in a "District Events" section, so `skip_sections` on school feeds removes them cleanly; a district org that is a union names buildings in its sections (`HW Events`, `HS Events`) or title prefixes. A school's footer can hold a mailbox in an address span, now dropped. School home pages have a "School Hours" block, the quickest bell source. An "Athletics" org (`/o/athletics`) can hold the only Arbiter link. A Smore issue inside a `ts-embed` iframe stored in page JSON isn't seen by the archive resolver. Virtual Backpack folders (`/documents/newsroom/virtual-backpack/<school>/<id>`) list PDFs with dated names; `backpack_parser` reads only Finalsite links.

## Hudson County (Kearny, Secaucus)

- When the district's own domain answers plain HTTP with a "Client Challenge", `<tenant>.sites.thrillshare.com/o/<alias>` serves the same pages to plain curl (`kearnysdnj`, `secaucuspublicschooldistrictnj`; the tenant is in the page source), and the `cms/events`, `cms/pages` and `cms/directories` APIs answer too.
- A third footer template (Secaucus): one `.contact-info-item-wrapper` row per item, the whole address on one line ("685 Fifth Street, Secaucus, NJ, 07094"). `discover_school_info` reads it.
- Kearny's school orgs each return the whole district directory (~580 people), the building only in the `department` chip ("Garfield", "Lincoln", "Kearny High"); the site narrows with `?filter_ids=<id>`, which the API honors (one id; a comma list returns nothing). The roster scan now narrows a school org's roster whose chips name two or more of the district's buildings.
- Secaucus's district org is a union of per-school sections ("Huber Events", "SHS Events") copying each school org's feed under new ids; its own "Events" section also carries one school's unprefixed items. `skip_sections` plus a `school_title_prefixes` entry.
- A calendar page can link the year PDF only as an `aptg.co` short link; `find_pdf_link` doesn't follow it, so the short link itself is the `calendar_pdf_url` (re-check each year).
- Kearny's district feed calls a no-student PD day "Staff Only - PD", now read as closed.

**Middlesex County (2026-11): Edison, Highland Park, Metuchen, Middlesex Borough, North Brunswick, Old Bridge, South Brunswick, Woodbridge.** Every one shows the "Client Challenge" on `www`, while `<tenant>.sites.thrillshare.com/o/<alias>` and the thrillshare `cms/pages`, `cms/events` and `cms/directories` APIs answer plain curl (tenant: the `<tenant>.sites.thrillshare.com` in document links, or a section slug's suffix). The org list is in the rendered home page as `"<name>","/o/<alias>","<alias>","<url>",<id>` tuples. Metuchen's own domain answered the full page once, then the challenge.
- Three calendar shapes. (1) Each school org repeats the district feed in a section of its own (North Brunswick "NBTSchools Events", Old Bridge and Edison "District Events"): school feeds take `skip_sections`. (2) The district org is a union of one section per school beside its own (Old Bridge "District & BOE", Edison "District Events", South Brunswick "District"): the district feed takes `skip_sections` naming every school section. (3) Every org has one "Events" section and schools type their own closures (Woodbridge): nothing dedups the school copies, which show as near-duplicates.
- An org that syncs a Google Calendar can list each event twice under different ids (Highland Park Bartle 13804): wire the Google ICS instead. A middle school org can carry hundreds of club and practice rows (Woodbridge's Iselin Middle, 651): `skip_title_prefixes`.
- Two NJ DOE schools can share one org (South Brunswick's Dayton and Deans, 32302) and so one feed, roster and menu. A closed school can keep a dormant org (Old Bridge Cooper 5185: no alias, empty directory).
- Absence lines can be a district page of `ts-card` blocks (Highland Park), a Google Sheet of extensions plus a Doc of Genesis steps (Middlesex Borough), or a tab per school on one high-school page whose tab text can be wrong (North Brunswick's Linwood tab shows Judd's number).
- Bell schedules: Google Docs whose `export?format=txt` gives tab-separated cells (Highland Park) or whose `export?format=html` `<td>`s read correctly (Middlesex Borough); two parallel `ts-text` blocks of labels and times, zipped by `<p>` (Edison High); a single PNG in a Doc (North Brunswick High).
- The footer can render a fax as a second unlabelled `tel:` link (Metuchen); the org's `organization_info` JSON names `fax_number` and carries the phone with its extension.
- Rendered pages run to ~5 MB of inline base64: a short-string grep ("wix") hits random runs. Page links can exist only inside escaped page JSON (South Brunswick's Smore issues), where the newsletter resolver finds nothing.
- FD MealPlanner location ids can be linked from a school's lunch page (Woodbridge: tenant 9, account 91, locations 426/428/430); the meals API's `accountName`/`altMenuName`/`gradeRanges` confirm a pair, but it answers only a valid account + location pair.
