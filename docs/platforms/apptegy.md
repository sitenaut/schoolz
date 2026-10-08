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
