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
