---
name: onboard-district
description: How to add a new school district or school to schoolz - the seed JSON import, town picker, calendar feed discovery, contacts. Load when onboarding, seeding or importing a district or school, or editing files in backend/seed/. Also holds the agent-based crawl workflow. Load the data-sources skill alongside it.
---

# Onboarding a district

**Read `docs/ONBOARDING_CRAWL_GUIDE.md` first** (the procedure; ~600 lines, generic). Per-platform and per-district findings are in `docs/platforms/` - read only the file for the platform you identify, never all of them.

## Workflow: orchestrator plus crawler subagents

The main session orchestrates; the crawling happens in `district-crawler` subagents (`.claude/agents/district-crawler.md`), so page dumps and platform notes stay out of this context.

1. **Scope.** Find the district's schools (NJ DOE directory CSV in `backend/seed/njdoe/`, the district site) and identify the platform from the homepage of each (generator meta, URL shapes, signal strings from the guide). Start `backend/seed/<district>.json` as a skeleton like `merchantville.json`. Check `docs/DATA_GAPS.md` and the `onboarded districts` memory so you don't redo a district.
2. **Fan out, capped at 3 at a time.** One `district` crawler for shared data, one `school` crawler per school. Give each the name, URL, platform, the sibling schools, and the platform file to read. Never run more: the scraper runs from the owner's home IP and was CAPTCHA'd by load once. Small districts (1-3 schools): one crawler per school is plenty; sequential is fine.
3. **Merge.** Each returns one JSON block (`seed_fragment`, `findings`, `gaps`, `needs_verification`, `new_platform_notes`). Merge fragments into the seed file yourself; crawlers never write. Treat `inferred` as unconfirmed (leave the field null unless the guide says otherwise) and spot-check two or three `confirmed` values against the page, since subagent reports can be wrong. Resolve conflicts between schools' fragments (shared calendar ids, a shared website_url) by hand.
4. **Import locally and run every job.** Import through Admin -> Import/export or `POST /admin/config/import`, then run-now each created job one at a time from `schoolz-scheduler-local` (not the API container; see `backend/scheduler/CLAUDE.md`). The guide's "Done means the scan works" section exists because hand-confirmed sources still shipped broken scans. Check `needs_verification` items here. Parser changes need the `content-extraction`/`data-sources` skills.
5. **Record.** Add `gaps` to `docs/DATA_GAPS.md`. Add `new_platform_notes` to the matching `docs/platforms/` file (or create one and add a row to the guide's table) in the same PR. The seed file is committed.
6. **Prod is a separate, human-approved step.** Stop after local verification and show the owner the summary. Prod import is `scripts/schoolz-api.sh prod POST /admin/config/import <file>` and the `deploy-schoolz` skill; never a direct DB connection.

## Import mechanics

The crawl guide says how to *find* each data point; this section is how it gets *in*.

Seed through **Admin → Import/export** (`POST /admin/config/import`) with a JSON file like those in `backend/seed/`: idempotent, admin-only, runs the same `_ensure_*_job` hooks as the forms, identical on local and prod (`scripts/schoolz-api.sh prod POST /admin/config/import <file>`). `IcsFeed.school_slug` (not an id) makes per-school feeds portable. Process fields with no newsletter source (absence method/phone, hours) are typed into the seed from the district's own pages. The optional `local_events` section upserts sources into an existing `local_events.refresh` job by name; it never removes one (that would delete its events) and isn't exported, since prod deliberately runs a different source list than local.

- **The picker groups by town, not district** (`District.towns`, `lib/towns.ts`) — a family shouldn't need to know their K-8 and high school are two districts. A town gets a chip only once it has a tracked elementary school; town copy (header, SEO) counts only chip towns.
- **Finalsite calendar ids are enumerable** on most sites: `/fs/calendar-manager/events.ics?calendar_ids[]=N` is a public GET, ids are the filter checkboxes' `value`s, `calendars.json` names them. Ids 1-2 are Finalsite sample calendars everywhere. Older sites hide the URL behind the subscribe button (see Data sources). A per-school feed repeats every district event **under the same UID**, so `district_calendar_scan` subtracts district-feed UIDs and stores the remainder `scope="school"`.
- **Rotation titles may carry the class order** (`Day 3 ( 3, 4, 1, LL, 7, 8, 5)`): `_ROTATION_RE` (backend) and `ROTATION_RE` (`lib/districtItems.ts`) allow a trailing parenthetical; group 1 stays the digit because `kids_schedule` reads it.
- **Contacts from the contact page** (`services/contact_page.py`): when a roster has no titled role, one Haiku call reads the school's "Contact Us" page (hand-typed layouts vary; tables flattened row-by-row first), and every person kept must have a name and email verbatim on the page.
- Known per-district gaps live in `docs/DATA_GAPS.md`; add to it when onboarding leaves one.

Per-source parsing quirks (menus, rosters, calendars, documents) are in the `data-sources` skill.
