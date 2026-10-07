---
name: onboard-district
description: How to add a new school district or school to schoolz - the seed JSON import, town picker, calendar feed discovery, contacts. Load when onboarding, seeding or importing a district or school, or editing files in backend/seed/. Load the data-sources skill alongside it.
---

# Onboarding a district

**Read `docs/ONBOARDING_CRAWL_GUIDE.md` first** — how to *find* each data point on a new district. This section is the *import* mechanics.

Seed through **Admin → Import/export** (`POST /admin/config/import`) with a JSON file like those in `backend/seed/`: idempotent, admin-only, runs the same `_ensure_*_job` hooks as the forms, identical on local and prod (`scripts/schoolz-api.sh prod POST /admin/config/import <file>`). `IcsFeed.school_slug` (not an id) makes per-school feeds portable. Process fields with no newsletter source (absence method/phone, hours) are typed into the seed from the district's own pages. The optional `local_events` section upserts sources into an existing `local_events.refresh` job by name; it never removes one (that would delete its events) and isn't exported, since prod deliberately runs a different source list than local.

- **The picker groups by town, not district** (`District.towns`, `lib/towns.ts`) — a family shouldn't need to know their K-8 and high school are two districts. A town gets a chip only once it has a tracked elementary school; town copy (header, SEO) counts only chip towns.
- **Finalsite calendar ids are enumerable** on most sites: `/fs/calendar-manager/events.ics?calendar_ids[]=N` is a public GET, ids are the filter checkboxes' `value`s, `calendars.json` names them. Ids 1-2 are Finalsite sample calendars everywhere. Older sites hide the URL behind the subscribe button (see Data sources). A per-school feed repeats every district event **under the same UID**, so `district_calendar_scan` subtracts district-feed UIDs and stores the remainder `scope="school"`.
- **Rotation titles may carry the class order** (`Day 3 ( 3, 4, 1, LL, 7, 8, 5)`): `_ROTATION_RE` (backend) and `ROTATION_RE` (`lib/districtItems.ts`) allow a trailing parenthetical; group 1 stays the digit because `kids_schedule` reads it.
- **Contacts from the contact page** (`services/contact_page.py`): when a roster has no titled role, one Haiku call reads the school's "Contact Us" page (hand-typed layouts vary; tables flattened row-by-row first), and every person kept must have a name and email verbatim on the page.
- Known per-district gaps live in `docs/DATA_GAPS.md`; add to it when onboarding leaves one.

Per-source parsing quirks (menus, rosters, calendars, documents) are in the `data-sources` skill.
