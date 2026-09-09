# Data gaps

Everything schoolz shows is sourced from somewhere real — a school's own website, a Smore newsletter, the district's calendar feed or transportation pages — never invented. This document is the honest inventory of where that sourcing is solid, where we had to build a workaround to get usable data out of an inconsistent source, and where a real gap still exists because the information simply isn't published anywhere we could find. It's written for whoever picks this project up next, and it's the technical backbone behind `docs/DISTRICT_COMMUNICATION_REPORT.md`, which makes the same case to the district in plainer terms.

Numbers below are a snapshot as of 2026-09-09 against 28 tracked schools (12 elementary, 3 middle, 2 high, 1 alternative, 10 private preschool/early-childhood providers) in one district (Cherry Hill Public Schools, NJ). "Coverage" means schoolz successfully found and parsed the thing; it does not mean the underlying school necessarily has the thing at all — several gaps below are gaps in what schools *publish*, not gaps in what schoolz looked for.

## Coverage snapshot

| Data | Coverage | Real gap or workaround? |
|---|---|---|
| School identity (name, address, phone, website) | 28/28 | Solid — scraped from each school's own Finalsite footer widget. |
| Staff directory | 27/28 schools with a real roster | Real gap: only one school's roster failed on last scan, and it's a transient failure (see "Known transient state" below), not a structural one. |
| Absence reporting method (email/phone/portal) | 3/28 determined | **Real gap.** Only 2 schools (email) + 1 (portal) have a confirmed method; the other 25 have never had it extracted, because it depends on a school's newsletter explicitly stating its absence procedure — most don't, or say it in a way the extraction prompt hasn't been tuned to catch yet. |
| Bell schedule (regular hours) | 28/28 have *some* hours | Both tiers below this one are the real gap. |
| Bell schedule (early dismissal / delayed opening times) | 2/28 (both high schools) | **Real gap.** Elementary and middle schools' delayed-opening/early-dismissal times aren't published anywhere we found — East and West happen to publish a clean bell-schedule PDF; nobody else does. |
| Bell schedule (period-by-period table, for "what period is it right now") | 2/28 (both high schools) | Same gap, one level deeper — even the two schools with a bell schedule PDF only get parsed for the day-level times; the full period table for those two was hand-transcribed from the PDF once, not auto-parsed (see "Manual transcriptions" below). |
| Parent/student handbook | 13/28 | **Real gap** for 15 schools, mostly preschools and a few elementary schools where no handbook could be found on the site or in a newsletter. |
| SACC (before/after-school care) | 12/12 eligible schools | Solid — SACC is K-5 only and every eligible elementary school has a row; sourced from one shared district handbook plus a per-school phone number. |
| Transportation / late bus | District-wide info: 1/1 district. School-specific late bus: 5/28 schools (3 middle + 2 high) | **Not a gap — a fact.** Late buses genuinely don't exist for elementary schools; the district confirms this on its own page. |
| Lunch menu | District-wide PDF: all 3 school tiers × 2 meal types. Newsletter-embedded: 1 school (Chesterbrook) | **Real gap** for the other 9 preschools — no menu found for them anywhere. |
| Logo/seal | 27/28 | 1 real gap (Mosaic Early Learning Center — no usable logo exists on their site at all, see below). |
| Smore newsletter tracked | 8/28 | **Real gap and a genuine adoption question** — see the Smore section below; most schools either don't use Smore or we haven't found their link yet. |
| District calendar (closures, early dismissals, board meetings) | 1/1 district, 2 feeds | Solid, but see "Discovery required real reverse-engineering" below. |
| Marking period / report card dates | 1/1 district, 36 items across 4 tiers | Solid. |
| PTA info in the app | 1/28 schools (Bret Harte) | **This is downstream of the Smore gap above**, not a separate one — PTA content only reaches schoolz when it appears in a newsletter we're tracking. See the district report for a much larger finding: most schools' *own* PTA pages are themselves stale or broken, independent of schoolz. |

## Manual transcriptions (not auto-discovered — a maintenance liability)

A few pieces of real, correct data are in the system *only* because someone read a PDF and typed the numbers in, not because a scan discovered them. These are the most fragile facts in the whole dataset:

- **The full bell-schedule period table** (`School.bell_periods`) for both high schools — 24 period-time pairs across regular/delayed-opening/early-dismissal, transcribed once from each school's published PDF. If either school revises its bell schedule, this table goes stale silently; nothing re-checks it. There's a validated admin endpoint (`PATCH /schools/{id}` with a `bell_periods` body) to correct it by hand, but nothing currently *notices* it needs correcting.
- **The district's day-rotation PDF for both high schools** (`hs_rotation.scan`) is at least a real recurring scan, not a one-time transcription — but the scan depends on that PDF keeping its current cell layout; the district's own PDF is labeled "Tentative — update as needed," so a format change would silently break parsing rather than erroring loudly.

## Discovery required real reverse-engineering (worth knowing if it ever breaks)

Some of the cleanest-looking data in the app came from sources that don't expose a public API and had to be found by watching what the site's own JavaScript does:

- **The district's calendar feed URL isn't in any page's HTML.** Finalsite's "Subscribe to calendar" button hands the `.ics` URL to `navigator.clipboard.writeText()` in JavaScript and does nothing else — the URL was found by scripting a real browser click and intercepting that clipboard write, not by reading markup. If the district ever changes calendar widgets, this breaks with no warning.
- **The staff directory's pagination looks like real server-side paging** (distinct URLs, `data-page` attributes) but is entirely client-side — re-fetching page 2 as a fresh request just returns page 1 again. Confirmed by comparing two "different" pages' first entry (identical). Fixed by keeping one live browser session open and clicking the actual "next page" control.
- **Two open-ended parsing rules that could plausibly land wrong data**: image blocks in Smore carry a hover-only "zoom" control whose text (`"zoom_out_mapShow in original size"`) was, for a while, silently winning over the real vision-extracted flyer content for *every image block in every newsletter*, with no error anywhere. This was caught only by a human manually checking one school's page against what got extracted. It's fixed, but it's a sharp reminder that a silent-failure class of bug like this can absolutely happen again in a different corner of the same pipeline, and the only reason this one was caught was someone looking closely at one specific school by hand — an oversight loop that doesn't scale.

## Known adoption/usage gaps (not something we can code our way out of)

- **Only 8 of 28 schools have a Smore newsletter tracked at all.** This is the single largest lever on how much of schoolz's "events, deadlines, PTA, procedures" content exists for a given school, and it's fundamentally an adoption gap, not a technical one — a school that doesn't run a Smore newsletter (or does, but we haven't found the link) contributes nothing to schoolz beyond its static website content, no matter how good the parsing pipeline is.
- **One tracked newsletter (Rosa International Middle School) has never successfully scanned** — 0 blocks parsed despite being in the tracked list. This needs investigation (dead link, changed URL, or a parsing failure that's been silently failing) rather than being counted as "tracked."
- **Cooper Elementary publishes a new Smore URL per issue** rather than one stable feed, and Clara Barton's principal turned out to follow the same pattern (her "official" link was an author profile page listing 40 separate newsletters, not a stable feed — see `CLAUDE.md`'s Smore section for the full story). Both need a human to re-add the current issue's URL by hand every time a new one is published; there's no automated way to detect "a new issue exists" for a school that works this way.
- **No live delay/alert feed exists anywhere on the district's site** — checked explicitly (searched for any `alert`-class element on the homepage and the transportation pages; found zero). Bus delays go out only as automated messages to whatever contact info a family has on file in Genesis, with nothing published for schoolz (or anyone else) to read. This is a genuine information gap for the district to consider closing, not something scannable around.

## Known transient state (not a real gap — noted for accuracy)

At the time this document was written, 19 scans (`school_info.scan` and `staff_roster.scan`, both on a 12-hour cron) show a `last_status` of `error`, all timestamped at the exact same instant. This is an artifact of this session's own backend container restarts happening to land on a scheduled cron tick, not a real, persistent failure — the next scheduled run (self-healing, no action needed) will clear it. Confirmed by checking that every failure shares one timestamp and that the underlying scan code works correctly against these same schools when triggered manually. Mentioned here only so a future reader checking `/jobs` doesn't mistake a one-time restart artifact for 19 newly-broken schools.

## Infrastructure gap: shared local database in tests — fixed

The backend's pytest suite runs against the same local Postgres the dev stack uses, rather than an isolated test database — this used to mean every run silently left behind throwaway test users/students/schools in the same tables the app's UI browses (confirmed to reach 169 leftover test accounts before being caught, directly causing a confusing debugging session where a real "Show me today" bug was mixed up with test-account noise). This is now fixed at the root: `backend/tests/conftest.py` wraps every test in a real transaction, rolled back afterward, so nothing persists regardless of which database the suite runs against. `backend/scripts/cleanup_test_data.py` remains checked in only to sweep up anything committed before that fix existed.

## Porting configuration between environments — solved

Every piece of centrally-managed configuration described in this document (tracked districts and schools, their config URLs, Smore newsletter links, bell schedules, SACC info) can now be exported from one environment and imported into another via `GET /admin/config/export` / `POST /admin/config/import` (`backend/routers/admin_config.py`), with a small CLI wrapper at `backend/scripts/migrate_config.py`. Import reuses the exact same job-creation helpers as the normal admin endpoints, so a ported district/school ends up with its scans already scheduled, not just its static fields set. It's idempotent (matched by district name / school slug / newsletter URL) and tested against a real full local export round-tripped back into itself with zero duplicate rows created. See the README's "Porting configuration to a new environment" section.

Deliberately out of scope for this: anything *discovered* by a scan rather than admin-entered (staff directories, documents, lunch menus, calendar events, extracted newsletter content) — that repopulates on its own once the ported scans run in the target environment, so there's no need to port it directly.

## What would most improve coverage, in priority order

1. **Get every school's absence-reporting method on record.** Right now 25 of 28 schools have no determined `absence_method`, which means the "report absence" action on those schools' pages either falls back to generic instructions or shows nothing at all — this is the single most-used action in the app and the biggest coverage hole in it.
2. **Find or request bell-schedule detail for elementary and middle schools.** Only the two high schools have it. If it isn't published anywhere, it likely needs to come from the district directly rather than being discoverable.
3. **Investigate Rosa's non-scanning newsletter** and re-verify Cooper's and Clara Barton's current issue links — three of eight tracked newsletters have a known problem.
4. **Expand Smore (or an equivalent) adoption** to the 20 schools with none tracked, or confirm which of them genuinely don't publish one at all so effort isn't wasted looking for something that doesn't exist.
5. **Find a lunch menu for the 9 preschools without one.**
