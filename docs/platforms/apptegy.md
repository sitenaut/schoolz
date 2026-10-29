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

