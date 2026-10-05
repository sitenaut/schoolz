# CLAUDE.md

Guidance for Claude Code working in this repository.

**What belongs here:** decisions and their rationale, non-obvious constraints, and bugs whose mechanism would cost real time to rediscover. **What doesn't:** anything derivable from the code, per-school data (that lives in the database), coverage counts, or traffic numbers (those live in Grafana and are stale the moment they're written). Dates are in git; don't date entries. Subsystem detail too long for every session goes in `docs/` with a pointer here.

**Local paths and personal identifiers never get committed.** No tracked file (docs, skills, scripts, comments, commit/PR messages) may contain a path into anyone's own machine — `C:\Users\…`, `/mnt/c/…`, `/home/<user>/…`, `/Users/…`, or a `~/…` that points outside the repo — nor a contributor's real name, OS/GitHub username, personal email, or personal account/org name (refer to roles: "the owner", "the dev branch"). Use repo-relative paths; scripts derive locations at runtime (`$PSScriptRoot`, `$(dirname "$0")`, `git rev-parse --show-toplevel`; `wsl` inherits the current directory). Anything machine-specific goes in the untracked `CLAUDE.local.md` (excluded via `.git/info/exclude`). The same goes for real people found in scraped data — no staff names in docs.

## Project

schoolz streamlines communication between parents and their school districts (South Jersey, starting with Cherry Hill), to better support kids' education at home. Which districts and schools are tracked is data — see the database, not this file.

## Architecture

React (Vite/TS) → FastAPI → Postgres. Two environments only: **local** and **prod**. No dev/stage tier; `main` is prod.

- `backend/` — FastAPI + SQLAlchemy async + Alembic (**Alembic is the schema source of truth**). Dual auth via `AUTH_MODE` (`backend/auth.py`):
  - `local` — email/username/password, self-serve `/auth/register`, bcrypt, HS256 JWTs. No Google SSO.
  - `supabase` (prod) — Supabase Auth handles Google SSO + password; backend verifies the Supabase JWT against JWKS (slow-path fallback to `/auth/v1/user`) and auto-provisions a `users` row on first sight. No MFA.
- `frontend/` — Vite/React/TS. `src/authConfig.ts` reads `VITE_*` at build time; `src/context/AuthContext.tsx` switches between local-JWT and Supabase auth. `frontend/focus/` is the kids' Focus app, served same-origin at `/focus/`.
- `scraper/` — standalone FastAPI + Playwright (headless Chromium), deliberately generic (`/fetch-html`, `/fetch-paginated`, `/fetch-raw`, `/health`). **No site-specific parsing lives there** — call `backend/scraper_client.py` and parse in the backend, so the scraper stays swappable.
- Three Fly apps: `schoolz-api` (process groups `app` + `scheduler`), `schoolz-web`, `schoolz-scraper`.

## Commands

```
./scripts/compose-local.sh up --build                    # postgres, migrate, backend, frontend, scraper
OBSERVABILITY=1 ./scripts/compose-local.sh up --build    # + Grafana/Mimir/Loki/Promtail/Alloy
SCHEDULER=1 ./scripts/compose-local.sh up --build        # + the cron scheduler (off by default)
./scripts/alembic_env.sh local revision --autogenerate -m "..."
./scripts/alembic_env.sh prod upgrade head
./scripts/verify-local.sh                                # full stack health, live auth, and test suite
powershell -ExecutionPolicy Bypass -File .\scripts\verify-local.ps1   # Windows equivalent
docker exec schoolz-api-local sh -c 'cd /app && python -m pytest -q'
cd frontend && npm run build && npm run test
./scripts/schoolz-api.sh <prod|local> METHOD PATH [body.json]   # authenticated API call (see API keys)
```

## Environment files

`env/` is entirely gitignored (not even `.example` variants) because some files hold real secrets. **`docs/ENV_SETUP.md` is the source of truth** — read it before touching env config. Root `.env.example`/`.env.prod.example` are tracked templates.

**Admin bootstrap:** locally, `ADMIN_EMAIL`/`ADMIN_USERNAME`/`ADMIN_PASSWORD` in `env/secrets.local.env` seed an admin on startup (idempotent, local auth only — `auth.py:seed_admin`). Prod's equivalent is `BOOTSTRAP_ADMIN_EMAIL`, which flags a Supabase email as admin on first login.

## Access model: public by default

Deliberate product pivot: **almost everything is public, no account needed.** The target workflow is "bookmark your kid's school page," not "log in to see anything." Registering is optional, only for the personal layer (your own kids, a narrowed calendar). Enforced in `backend/auth.py` + per-router:

- **Public** — every `GET` on schools/districts/calendar/newsletters/local events/directory. `GET /calendar` uses `get_optional_user` (returns `None` rather than 401) so it *degrades*: a logged-in guardian gets it narrowed to their schools, an anonymous visitor sees everything. An explicit `school_id` narrows either way.
- **Authenticated** — students, guardian links, invites, notifications, account settings. Registering never grants admin.
- **Admin** — creating/editing District/School/SmoreNewsletter, any `run-now`, `/scheduled-jobs`, and Gmail connection + email scanners (connecting an inbox is data-source management, not a guardian task). Scanner rows stay owner-scoped so two admins don't see each other's captures.
  - `User.is_admin` means **super admin**: every permission, and the only tier that can manage users/roles (`require_super_admin`, `routers/admin_users.py`). Nobody can remove their own super admin, which guarantees one remains.
  - Everyone else gets admin access through **`Role`s**, each a set of keys from the fixed catalog in `backend/permissions.py`. Permissions live in code because real endpoints must check each one; roles are data. Read/write pairs where an area has admin-only reads (`x.manage` implies `x.view` via `permissions.expand`): GETs check `.view`, mutations `.manage`, via `require_permission("<key>")` (a cached factory, so tests override a gate by identity). `/auth/me` returns `permissions` for the UI (`lib/permissions.ts`, `AdminLayout` tabs, `RequireAdmin permission=…`). Users/roles management is deliberately not grantable, so no role can mint admins. Scoping is by *function*, not by school/district. Roles take effect on the next request (no token claims).
- **API keys** (`ApiKey`, `routers/admin_api_keys.py`) — so a script or agent can change prod, where `/auth/login` can't be scripted (Supabase-only). A key acts as its creator narrowed to the permissions ticked (intersected at request time, so demoting the creator shrinks the key) and **never passes `require_super_admin`**, so no key can manage users, roles or keys. `szk_` prefix, only the SHA-256 stored, optional expiry; requests log `api_key_id`.
  - Get one with **`scripts/schoolz-api.sh login prod`**, a device flow built because the owner is often on a phone: it prints a code and an `/admin/api-keys/approve?code=` link, a super admin approves in any signed-in browser, and the script writes the key into gitignored `env/api-keys.env` (0600) — it never passes through chat or the screen. The key is minted when the script collects it (`ApiKeyRequest`, 10-min window, single use), so plaintext is never stored. `/auth/device/start` and `/token` are unauthenticated, bounded by a cap on open requests. `RequireAdmin` carries `?next=` through login so the link survives an expired session. The script passes the key to curl on a file descriptor so it never appears in argv.
  - **This is the sanctioned route for prod admin changes — never a direct DB connection.**

**The chatbot (`POST /chat`) straddles the tiers.** Anonymous callers get the public MCP tools plus `find_local_events`. A signed-in caller also gets personal tools (`services/chatbot_personal.py`) that call the existing authenticated GET routes in-process **with the caller's own bearer token** — no new access code, so the chatbot can never see more than that person could by clicking around. These tools are never registered on the public `/mcp` server, which holds no credentials. Read-only; a bad token degrades to public instead of 401ing.
- **Prompt caching** (`services/chatbot.py`): one breakpoint on the stable system block caches every tool definition, shared across visitors; anything varying (today's date) goes after it. `find_local_events`' live category list is names-only, sorted, re-read hourly, so tool definitions stay byte-identical (that's also why it lives in `chatbot_personal.py`, not the static-docstring MCP server). The anonymous prefix is barely over Haiku 4.5's 4,096-token cache minimum — trimming it below silently stops caching. Check `cache_read_tokens` on `chatbot_usage` log lines in Loki.
- **Providers are switchable** in /admin → Chatbot (`app_settings` row `"chatbot"`, `services/chat_settings.py`), **separately for anonymous and signed-in** — signed-in chats carry children's data, so moving public traffic to a cheaper provider must not silently move that too. `services/chat_providers.py`: history stays in Anthropic's message shape (what the widget replays); the Gemini adapter translates per call. Provider-only fields ride on history blocks under `_`-prefixed keys (e.g. a Gemini tool call's extra fields, echoed back in case they carry a thought signature) and are stripped before anything goes to Anthropic. The compare panel runs the real loop; judge over several runs, answers vary.

Frontend: public pages are plain routes. `RequireAuth` gates personal pages; `RequireAdmin` gates `/admin/*` (a logged-in non-admin bounces to `/`, not `/login`). Pages branch on `useAuth().user` to choose `/schools/mine` vs `/schools`, so an anonymous visitor never calls an endpoint that would 401.

## Domain model

**Students are shared, never owned.** A `Student` is the canonical record for a real child; each guardian has their own `GuardianStudentLink`. Deleting your link removes only *your* view.

- **Auto-matching** — `Student.match_key` = normalized `first_name|last_name|student_id`. A matching add links to the *same* Student with no approval gate, and every already-linked guardian gets a `guardian_matched` `Notification`, so it's never silent. The divorced-parents scenario (shared kids visible to both, non-shared kids private, one parent's delete doesn't affect the other) is covered in `tests/test_students.py`.
- **Guardian invites** (`routers/invites.py`) — per-child, token-based, 7-day expiry. The unauthenticated preview shows only first name + last initial, so an invite link can't be used to fish for a child's identity. The frontend preserves the target across register/login via `?next=`.
- **Student accounts** (`routers/student_accounts.py`) — `Student.user_id` points at the student's own `User`; the account *is* that pointer. Stricter than guardian invites: the logged-in email must match the invited one, one account per student, and a guardian of that student can't claim it. `bucket3._get_own_student` allows guardian **or** student, so both see identical data; `viewer_role` tells the UI which guardian-only controls to hide. Deleting a student's login nulls `Student.user_id`, never the student.
- **`Student.school_id` is required** and chosen from tracked schools, never free text.
- **Per-account vs per-student keying is a privacy decision.** A `Student` row is visible to every linked guardian, so anything that is one person's own preference is keyed on **`user_id`**, never `student_id`: `CourseDisplayPreference` (rename/recolor a class; follows the person across devices, invisible to other guardians), `ClassPaymentTick` (each guardian tracks their own "have I paid this"). Facts about the child are keyed per student so every guardian sees the same thing: `StudentSpecial` (which special — Art, PE, … — falls on each rotation day; typed in on My Children, since specials appear nowhere in captured Genesis pages). Late policies are per *(student, course)* — see below.

### Kids view (`services/kids_view.py`, `routers/bucket3.py`, design in `docs/KIDS_VIEW_V2_DESIGN.md`)

Pure rules, unit-tested in `tests/test_kids_view.py`. After any parser change, run **Re-read imported pages** (`POST .../bucket3/reprocess`) — import dedups by content hash, so stored captures need re-extraction.

- Classroom never says "Missing" (it's derived: past due, not done). A person's mark (`ChildWorkItemProgress`) beats Classroom/Genesis in **both** directions. Missing/Done are filtered to the current marking period. A Genesis "0.00%" with no graded entries is no grade.
- Teacher emails come only from the school's `StaffMember` directory — ambiguous matches resolve to none, never a guess.
- **Suggestions** (`services/kids_suggestions.py`, Haiku): tier A is cached per district course code + normalized title so one generation serves the whole class, and only title + course name are ever sent; tier B is never stored.
- **Late-work policies** (`CourseLatePolicy`, `kids_view.late_credit`) — per *(student, course)*, not shared per section: one family transcribes their own paper handout, so a mistyped rule must not reach another family, and IEP/504 accommodations genuinely differ. Six shapes (`full_credit`/`flat`/`daily_decay`/`window`/`tiered`/`not_accepted`). `late_credit()` returns **None for "no policy on file"** — "unknown" must stay distinguishable from "known to be zero", because only the latter may hide work. Pasting the syllabus paragraph (`/late-policies/parse`, Haiku) **never saves**; it proposes next to the teacher's own sentence and a person confirms.
- **Focus prioritisation**: due-soon work is the only work where acting now still protects full credit, so it always wins the limited slots; past-cutoff work is dropped from the Focus tab (it's in Details) rather than sitting there as guilt with no action attached. Progressive disclosure: a Focus card is Subject + Title + Checkbox; details only in the tapped sheet.
- **Per-assignment teacher exceptions** (`WorkItemLateException`) — "turn it in before the marking period ends and I'll take it". Overrides the class policy for that item **and** beats `in_current_marking_period` (such promises routinely name work due in the *previous* period, exactly what the staleness filter drops first), and ignores `MAX_PLAUSIBLE_DAYS_LATE` (that guard exists because a due-date year is *inferred*; a person typing what a teacher said isn't). A human grant outranks every automatic rule. `credit_pct` null means the deadline moved but points weren't mentioned: the class gradient still applies minus the cutoff; with no policy or no gradient (`not_accepted`), "I'll take it" means full credit. The exception still expires on its own date.
- **Assignment point values** (`ChildWorkItem.points_possible`, `bucket3_extract.py:extract_classroom_detail_points`) — the classwork grid/stream cards never carry points; they exist only on the item's detail page (`.../a/<id>/details`), which backpack-capture already crawls and publishes. Shape after the `"<teacher> • <posted date>"` line: nothing, a bare `"<N> points"` (ungraded), or `"<earned>\n/<possible>\n<earned> points out of possible <possible>"`. Only `possible` is kept — real grades belong to Genesis's `ChildGradeEntry`. `null` means "not captured", never zero, so `courses.ts:byPointsDesc` sorts unknown last. Points break ties only *within* a date-urgency group, never above it.
- **"I don't know what this is about"** (`services/help_requests.py`) — the student picks which *kind* of stuck from a five-item menu and the backend writes the teacher email; they never have to articulate the confusion, which is frequently the whole problem. Deterministic templates, no model — the wording is the product and must work with no API key. Sent via `mailto:` from the student's own mail app; schoolz never transmits or stores the body. `HelpRequest` records only that an ask of that kind happened (so patterns are visible without anyone reading a kid's mail). Guardians get a `help_asked` notification naming the kind, never the text.
- **Eastern is PowerSchool, not Genesis** — Kids View/Backpack Capture parsing doesn't cover its students.

### Schools, districts, content

- **`District`** exists because some resources are published district-wide per school type (lunch menus are the confirmed case). `School.district_id` + `School.school_type` (`elementary|middle|high|alternative|other`) is what makes `GET /schools/{id}/lunch-menu` resolve automatically.
- **`School.slug`** is derived once at creation, never regenerated (a permalink, not a label). `routers/schools.py:resolve_school` resolves id **or** slug in one query.
- **`School.short_name`** — `derive_school_short_name()` strips type suffix and district prefix, but it can't tell a droppable middle initial from a real given name, so it's editable via `PATCH /schools/{id}`.
- **Content scoping** — `SchoolContentItem.scope` is `school` or `district`. District items dedupe one row per `(district, category, start_date)` because every school's newsletter reports the same holidays — except `^Day \d$` titles: rotation feeds put a `category="event"` marker on nearly every school day, and keying on them either crashed with `MultipleResultsFound` or dropped real events as "duplicates" of "Day 3". `GET /schools/{id}/content` unions a school's items with its district's.
- **High-school class pages** (`SchoolClassYear`, `ClassPayment`, `routers/class_years.py`, design in `docs/HS_CLASS_PAGES_DESIGN.md`) — organized by graduating class, not grade, because the school's own materials describe multi-year things relative to the cohort and a grade number silently means different kids every July. `SchoolContentItem.applies_to_grad_years` mirrors `applies_to_school_types` (null = whole school). `services/class_years.py:CLASS_PAGE_SOURCES` (`school_ics`, `hs_announcements`, `hs_activities_site`) are too club-level for general views: off by default in `/calendar` and `/content`, on via `include_class_sources=true` and on the class page. `hs_activities_site` crawls Google Sites with plain `httpx` (server-rendered) — never the scraper.

## Onboarding a district

**Read `docs/ONBOARDING_CRAWL_GUIDE.md` first** — how to *find* each data point on a new district. This section is the *import* mechanics.

Seed through **Admin → Import/export** (`POST /admin/config/import`) with a JSON file like those in `backend/seed/`: idempotent, admin-only, runs the same `_ensure_*_job` hooks as the forms, identical on local and prod (`scripts/schoolz-api.sh prod POST /admin/config/import <file>`). `IcsFeed.school_slug` (not an id) makes per-school feeds portable. Process fields with no newsletter source (absence method/phone, hours) are typed into the seed from the district's own pages. The optional `local_events` section upserts sources into an existing `local_events.refresh` job by name; it never removes one (that would delete its events) and isn't exported, since prod deliberately runs a different source list than local.

- **The picker groups by town, not district** (`District.towns`, `lib/towns.ts`) — a family shouldn't need to know their K-8 and high school are two districts. A town gets a chip only once it has a tracked elementary school; town copy (header, SEO) counts only chip towns.
- **Finalsite calendar ids are enumerable** on most sites: `/fs/calendar-manager/events.ics?calendar_ids[]=N` is a public GET, ids are the filter checkboxes' `value`s, `calendars.json` names them. Ids 1-2 are Finalsite sample calendars everywhere. Older sites hide the URL behind the subscribe button (see Data sources). A per-school feed repeats every district event **under the same UID**, so `district_calendar_scan` subtracts district-feed UIDs and stores the remainder `scope="school"`.
- **Rotation titles may carry the class order** (`Day 3 ( 3, 4, 1, LL, 7, 8, 5)`): `_ROTATION_RE` (backend) and `ROTATION_RE` (`lib/districtItems.ts`) allow a trailing parenthetical; group 1 stays the digit because `kids_schedule` reads it.
- **Contacts from the contact page** (`services/contact_page.py`): when a roster has no titled role, one Haiku call reads the school's "Contact Us" page (hand-typed layouts vary; tables flattened row-by-row first), and every person kept must have a name and email verbatim on the page.
- Known per-district gaps live in `docs/DATA_GAPS.md`; add to it when onboarding leaves one.

## Scheduler and scans

Domain-agnostic scheduler (`backend/scheduler/`, ported from billz): `registry.py` (kind → handler via `@register_job`; handlers in `scheduler/jobs/`), `runner.py` (Postgres advisory-lock execution, `run_job_now()`), `entrypoint.py` (separate process, 30s reconcile against `scheduled_jobs` — **no restart needed** for job changes). Runs as its own compose service and Fly process group. **Locally it's opt-in** (`SCHEDULER=1`): left on, it re-ran every scan from the home IP on prod's cron and Google CAPTCHA'd that network. Test a scan with its run-now instead.

- **Advisory-lock keys must be deterministic** — `hashlib.sha256` of the job uuid, never `hash()` (randomized per process), or run-now and the scheduler never exclude each other.
- **Three-state results**: a handler returning a string starting `"WARNING:"` gets `warning` — "fetched fine, found nothing" must not look like success.
- **Stable error codes** (`scheduler/errors.py`): `classify_exception()` maps exceptions to `(code, stage)`, walking `__cause__`/`__context__` since `scraper_client` re-raises. Handlers can raise `ScanError(code, msg, stage=...)`; non-fatal problems call `record_parse_issue()`.
- **Stuck runs** are reaped after 45 min keyed on `COALESCE(last_progress_at, started_at)`, so a long run that checkpoints survives — but a single long step has no heartbeat inside it. Don't force-error a slow run-now on a hunch; check for real evidence.
- **Auto-scheduling**: setting a URL on a School/District creates its scan job (`_ensure_*_job` in `routers/schools.py`/`districts.py`). A never-run job whose first fire is over 12h away runs on the next tick (`runner.queue_first_runs`). **Changing an `_ensure_*_job` constant doesn't update existing rows.** A disabled job keeps its id, so `_ensure_*_job` never recreates it.
- **Cadence is tiered and spread** (`scheduler/cron.py:public_scan_cron`): minute — and for weekly/daily kinds hour and day — come from a hash of kind + target. Heavy Chromium scans of rarely-changing pages are **weekly** at night (never 1–2 AM ET: DST skips/repeats it); menus/givebacks/activities site **daily** 3–5 AM; cheap calendar feeds **12h**; `hs_announcements` (the only same-day source) has its own override; Smore stays weekly by explicit instruction. Why: all scans once fired at :00 against one 1GB Chromium and the heaviest sites failed `site_did_not_load` every burst while their run-nows succeeded. The job form still defaults to `0 */12` — pick another minute for a hand-made job. `scraper_client` caps in-flight requests at 3 per process, budgets 2× `timeout_ms` (the scraper applies it to `goto` *and* `wait_for_selector`), retries 502/503/504, and both `fetch_html` and `fetch_paginated` fall back to the droplet/Pi.
- **Deleting a job is safe by schema** — every `*_job_id` FK is `ON DELETE SET NULL`.
- **`ScheduledJob.next_run_at` is display-only.** APScheduler triggers from `cron_expr`; force runs via `run-now`.

**Newsletters.** `smore.scan` is the preferred path (public URLs, scraper only). `email.scan` needs a connected Gmail (read-only) and exists to *discover* newsletter links; `EmailScanner.school_id`, when set, auto-creates the discovered link's `smore.scan` job.
- **A new URL per issue is the common case.** Most tracked schools publish each issue at a fresh Smore URL, often weekly, and the job only re-checks the URL it's given — so each needs its URL swapped by hand per issue or a Gmail scanner to catch it. `smore.com/u/<username>` is an author profile, not a newsletter; issues live at `/n/<code>`.
- **An expired Smore link goes silent, not failed** — it renders a page with no `.block-wrapper`, indistinguishable from "nothing new". Zero blocks *fetched* is therefore `WARNING[smore_no_blocks]`.

## Content extraction

`content_extractor.py` turns new `SmoreBlock`s into `SchoolContentItem`s: a Claude vision pass over new image blocks, then one structured tool-use call over block text + vision output. Runs **once per newsletter**, shared/public — the point is not re-running Claude per parent.

- **`temperature=0`**; the prompt demands every bullet in a dated list and at least one item per flyer.
- **`items` is FIRST in the tool schema.** Fields generate in schema order, and a long newsletter can hit `max_tokens` mid-response; with `items` last, a real newsletter produced *zero* items. `max_tokens=8192`, chunks of 12 blocks, `stop_reason == "max_tokens"` → `WARNING`.
- **A tool schema's `"required"` isn't enforced**, even with forced `tool_choice` — always `item.get(...)` with per-item skip + `record_parse_issue` (a bare index once dropped a whole crawl's items).
- **Dates are local, not UTC.** The model returns bare ISO strings in school-local time; `_parse_date` attaches `America/New_York`. The frontend formats via `lib/calendar.ts:localDateKey` and anchors menu dates at noon UTC, never raw browser `Date` math. `is_all_day` is inferred from whether the string has a time, not the model's boolean.
- **Stale years roll forward.** Flyers reuse artwork with last year's date; the item then superseded the correct row and the event vanished from forward views. `_correct_stale_year()` rolls dates >30 days stale forward (5-year cap), and `_may_supersede()` won't let a past-dated item retire an upcoming one.
- **Corrections via supersede** — block dedup is exact-hash, so a typo fix is a new block; the call sees current items and can set `supersedes_item_id` (old row → `is_current=False`).
- **Status titles force `scope='district'`** (`services/school_status.py:is_status_title`) before dedup — closures/half-days are never one school's news. Its own regex set, *not* shared with `school_today.py:classify_day`, whose precedence (closed beats early dismissal) breaks on "EARLY DISMISSAL - Staff In-Service".
- **Links are verified, never trusted to the model**: `_find_link()` checks for a real anchor then a bare-URL regex on any block type; `link_url` is backfilled from the source block. Portal URLs come from `_KNOWN_PORTAL_URLS`, never the model.
- **Image blocks:** a hover "zoom" control once made every image block's `text_content` a junk string that beat the vision output, silently dropping every flyer. A YouTube block's play icon is a `data:` URI `<img>` — the real content is on `data-video-title`/`data-video-original-url`. A failed vision extract stays pending and warns (it used to be marked done, permanently). Media type is sniffed from bytes, not `Content-Type` (Smore labels PNGs `image/jpeg`).
- Prefer determinism where achievable (e.g. `_parse_lunch_menu_days` regex-splits model output instead of a second call); event-vs-reminder classification varies run to run and isn't worth chasing.
- **Known gap:** only closures/half-days dedupe across sources; an ordinary event reported by both the district feed and a newsletter in different words double-counts.

## Data sources and their quirks

- **Smore** — client-rendered Svelte, no API/RSS; scraper with `wait_for_selector=".block-wrapper"` (present on every block type).
- **Lunch menus** — one PDF per (grade band, meal type) per month; discovery anchors on the `-MS-Breakfast`-style suffix to tolerate real filename typos; parsed as a native `document` block; deduped on PDF URL. A bare month+year PDF counts as the type of a single-type district. `LunchMenu` also supports school-scoped rows. **SchoolCafé** (`District.schoolcafe_shortname`, `services/schoolcafe.py`) is a public JSON API, no model; only unambiguous school-name matches count. **FD MealPlanner** (`School.fdmealplanner_location` = `tenant/account/location`): the per-day `/meals` endpoint answers a bare request (only the one-time org search needs the client-encrypted token); items on ≥60% of the window's days are standing options and dropped so the rotating entrée shows; the endpoint clamps to its `monthId`, so one call per month.
- **Staff rosters** — Finalsite `?const_page=N` pagination *looks* server-side but is client-side (page 2 returns page 1), hence `/fetch-paginated` clicking `.fsNextPageLink` in one session. `StaffMember.title` is `None`, never `""`. `staff_roles.classify_role` (narrow, for the "Who to contact" grid) vs `classify_directory_category` (coarser, for directory filters, derived at query time so keyword tuning needs no migration/backfill).
- **School documents** — discovery tries site nav, then already-parsed Smore blocks (some handbooks exist only as a Google Doc link in a newsletter). Lookups are scoped to `<main id="fsPageContent">`, or a footer Drive link gets attributed everywhere. Max `academic_year` wins; nav and newsletter genuinely disagree.
- **School info** — Finalsite footer widget. Pages have **two** `<footer>`s (first hidden), so wait on `.fsLocationAddress`. Logo is the first `<header>` `<img>`, skipping a Google Translate badge.
- **District calendars** — on older Finalsite sites the `.ics` URL is never in the page; the subscribe button hands it to `navigator.clipboard.writeText()` (found by intercepting that write): `https://{domain}/fs/calendar-manager/events.ics?feed_id={uuid}`. `District.ics_feeds` carry `school_types`. Dedup runs both ways: the feed *claims* a matching newsletter row; `external_uid` makes re-scans idempotent.
- **Marking periods / transportation / preschools** — deterministic BeautifulSoup, no LLM, so dates can't be mis-zipped to columns. Real gremlins (NBSP in headings, weekday-prefixed dates, footnotes glued to dates) have fixtures in `tests/fixtures/`.
- **HS day rotation** — pdfplumber word coordinates; entries snap to the *nearest* month header (at-or-left mis-assigned months), headers sharing a line with entries are peeled off first. The sheet is "tentative", so vanished rows are deleted.
- **School events doc** (`services/school_events_doc.py`) — a year-at-a-glance Google Doc, regex-parsed. Three columns interleave in the txt export, so only each line's own date counts. Closures/breaks skipped (district feed owns them), month-only lines skipped, vanished lines deleted, an empty parse never prunes. Not a class-page source.
- **Google Sites** — server-rendered, plain httpx. Text extraction recurses only into *inline* descendants and lets each nested block be visited on its own; skipping any block with a nested block descendant discarded real loose text. "Button" widgets have no `href` server-side (resolved by a `jsaction` handler) — a known gap.
- **Weather** (`services/weather.py`) — NWS hourly over the school-day window (adjusted for early dismissal / delayed opening) + EPA UV by ZIP; keyless, deterministic what-to-wear rules. `School.latitude/longitude/nws_grid` filled by `school_info.scan` (reset on address change): Census geocoder, then Nominatim. Cached per gridpoint for an hour with a short timeout. No hours on file → "morning/afternoon", never a guessed bell time. After the window closes, and on weekends/closed days, shows the next school day (`pick_weather_day`).
- **Due-date years** (`bucket3_extract.resolve_due_date`) — Classroom prints the year exactly when month/day would be ambiguous; an explicit year must win over the Jul–Jun inference, or last year's work reappears as current (and, via `late_credit`, can hide live work). `kids_view.MAX_PLAUSIBLE_DAYS_LATE` guards bare dates.
- **Chesterbrook's own files** (`special_events.scan`, `services/special_events.py`) — its Calendars & Menu page lists each month's special-events calendar *and* lunch menu PDF, both read by one scan; menus are stored as the school's own `LunchMenu` with portion sizes stripped. The page ignores `?mm=` (every month's URL serves the same list), so a PDF's month comes from its filename; and it lags the uploads (October's menu sat under `wp-content/uploads/.../2026/10/` while the page still listed September), so a missing month is probed at its predictable WordPress upload path.
- **SACC** is deliberately not a recurring job — a one-off script; re-run by hand if the handbook changes. Only `site_phone` is per-school.

## Local events (/local)

Community events — **public, no auth dependency at all** (no per-viewer personalization). `backend/local_events/` is a **port of billz's `events/` pipeline** and `local_events.refresh` takes billz's `events.refresh` params verbatim (Scans → **Import from billz**). Per-source notes, scraping infra and the playwright-scraper deploy pipeline: **`docs/LOCAL_EVENTS_SOURCES.md`**.

- Admin UI is billz's: JSON params editor + **Test fetch** (`POST /scheduled-jobs/test-fetch`, a dry run with per-source status). Test before saving.
- Rendering goes to the shared Playwright droplet first, schoolz's own scraper second; the residential Pi is opt-in per call.
- **Deleting a job, or removing a source from its params, deletes that source's events** (`local_events/prune.py`), by source name across all remaining jobs. Disabling keeps them. **`prune.SOURCE_KEYS` must list every `*_sources` key** or every job edit deletes that source's events as orphaned (`tests/test_placewise_source.py` checks this).
- A failed source makes the run `WARNING` (billz only marks it `-1`).
- **Local compose scraper binds `0.0.0.0`**: the image binds `::` for Fly's IPv6-only 6PN, and asyncio makes that socket IPv6-only locally.
- **`uvicorn --reload` watches `backend/` incl. `tests/`**, so editing any file kills a run-now job in the API process. Run long jobs from `schoolz-scheduler-local` (`SCHEDULER=1`).

## Frontend

Built around one question: what does a parent need at 7:40 AM with one hand. Home is the **Today feed** — one day-card per school from `GET /schools/{id}/today` (one request per school). Everything renders inside `components/AppShell.tsx` (bottom tabs on mobile, left rail ≥900px).

- **"My schools" without an account** (`lib/mySchools.tsx`) — slugs in `localStorage` (survives closing the browser, no server round-trip). Tracks *picked* and *hidden* sets so a school added later is visible automatically; all hidden falls back to showing all.
- **Today renders in place with no schools picked** (a picker prompt, not a redirect), so the homepage always has indexable content.
- **School page order is deliberate — actions first, reference last**: sticky actions → week strip → reminders → coming up → who to contact → SACC → documents → newsletter leftovers. Documents flag "may be outdated" on academic-year mismatch.
- **Content in a collapsed accordion is content that doesn't exist** — a lunch menu rendered under "More" was invisible until a user asked.
- **Shared filters**: "Exclude district" (off by default; key `schoolz_exclude_district_v2` because old saved values were on-by-default) hides board/committee noise but never closures, half-days, or grading dates, and governs Today, the week strip and school page too. "Show day rotation" is Calendar-only.
- **District items are labeled per school** (`lib/districtItems.ts:expandItemRows`): a type-restricted item expands to one row per matching active school **in its own district** — "Day 3 [Bret Harte]" beside "Day 2 [East]", never "Elementary", never one district's rotation on another's schools.
- **Staff directory** (`/directory`) — answers "who is the middle-school nurse" when the school is the unknown. Search/filter/paging are server-side (too big to ship to a phone). Tokens AND across fields; facet counts are computed before the category filter so a chip always says what picking it gives.
- **Modals and the iOS keyboard** (`components/ui/Modal.tsx`, every dialog incl. chat). iOS covers the layout viewport rather than shrinking it, so the backdrop is fitted to `window.visualViewport` **vertically only and only at scale 1** — pinning all four edges (`068b297`) put the sheet off-screen when zoomed and was reverted (`33fe008`); don't widen it. Scroll lock pins `<body>` (`position: fixed; top: -scrollY`); `overscroll-behavior: contain` on `.modal-body`/`.chat-scroll`; `.chat-body` is `flex: 0 1 60vh` so the list shrinks, not the input. Playwright can't raise a keyboard: override `VisualViewport.prototype` and dispatch `resize`.
- **No form field under 16px on touch** — iOS zooms on focus and never zooms back. One global `@media (pointer: coarse)` rule, last and `!important`, at the end of `frontend/src/ui.css` **and** `frontend/focus/src/styles.css`. Never use `maximum-scale=1` (kills Android pinch-zoom). A new stylesheet/app needs the same rule.
- **`AbsenceButton`** adapts to `School.absence_method`: prefilled `mailto:`, `tel:`, portal link, or raw instructions.
- **Admin UI kit** (`frontend/src/ui.css`, `components/ui/`): Modal, ConfirmDialog, PageHeader, SectionCard, Field, Badge, Switch, Toast, DataTable. Row actions use `.btn.icon` (optionally `.danger`); there is no `.icon-btn`. Jobs UI's point is the **Runs tab** (error code, stage, traceback); rows label targets ("Staff roster scan · Bret Harte"), never UUIDs.
- **Account** is auth-mode aware (Supabase vs local bcrypt). Local has no mailer, so `/auth/forgot-password` returns the token in the response, while still 200-with-null for unknown emails (no enumeration). Deletion removes only what the user *owns*; shared rows survive with provenance nulled; deleting the Supabase identity needs `SUPABASE_SERVICE_ROLE_KEY`.
- **Community submissions** (`POST /submissions`, public, 15MB cap, bytes in the row — no object storage yet) land `pending` and **never feed extraction automatically** — curation is the point. The review page (`/admin/submissions/:id`, `services/submission_review.py`) reads an upload into *draft* items (`CommunitySubmissionItem`) and only an explicit Publish of ticked drafts writes `SchoolContentItem`s (`source="community"`). The model only reads; what looks wrong is decided in code (`item_flags`/`note_flags`), because the real failures are a handwritten date over a printed one, a printed weekday that's wrong for its date, and a sender's note naming a date the page doesn't. It calls Opus through `extra_body` since the pinned SDK predates `output_config`. `/contact` uses raw `fetch()` multipart because `apiFetch()` forces a JSON `Content-Type`.

**UI reference template:** before building admin-style UI, check the purchased Katalyst template (zip outside the repo; location in `CLAUDE.local.md`, ask if missing). Grep `src/shared/ui/` and `src/modules/**/ui/` for the closest analog. Inspiration rebuilt on this app's CSS custom properties, **never imported** — Tailwind is deliberately not a dependency; `styles.css` tokens follow its palette.

**Verifying UI with no browser on the host:** build, `docker cp` the dist into `schoolz-web-local`, drive it from the `scraper` container's Playwright, proxying `localhost:8000` → `backend:8000` via `page.route` (adding CORS headers) with an admin JWT in localStorage.

## Observability

`backend/telemetry.py` sets up OTel (traces/metrics/logs, OTLP/HTTP) for `app` and `scheduler`, and **no-ops unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set**. Custom instruments in `backend/observability.py`; `scraper/telemetry.py` is a deliberate trimmed copy. Prod is Grafana Cloud (stack shared with billz, tagged `service.namespace=schoolz`); dashboards and alert rules in `grafana/cloud-dashboards/`. Plan in `docs/OBSERVABILITY_PLAN.md`.

- **Metric-name trap.** Prod once emitted old HTTP semconv names while dashboards/alerts used the stable ones — empty panels, alerts that could never fire, no error. Fixed with `OTEL_SEMCONV_STABILITY_OPT_IN = "http"` in `backend/fly.toml`. **If a panel goes blank, check which spelling prod emits first.**
- **10k active-series budget**: `_metric_resource` excludes `service.version` (rolling deploys would duplicate series); scraper metrics omit `host` (domain detail belongs in traces/logs); `_metric_views` drops unused histograms and compacts latency buckets.
- **Backend log fields are OTel structured metadata** — the body is just `http_request`, so `| json`/`| logfmt` find nothing. Query metadata directly. `trace_id`/`span_id` must be in the formatter's `fmt` or they never reach the line.
- **Faro RUM** pinned `1.19.0` (2.x needs react-router v7+; we're on v6). `FaroRoutes` is undefined when RUM is off, so `telemetry.ts` exports plain `Routes` when `FARO_URL` is empty. **Mandatory scrubbing**: `scrubUrl()` drops the whole `#hash` (Supabase OAuth tokens), strips token-ish params, collapses `/invites/<token>`. Use `auth_state` (`pending`/`authenticated`/`anonymous`/`timed_out`), not `logged_in`, which mislabels exactly the sessions where auth never resolves.
- **Collector proxied same-origin** (`/rum/collect`, `FARO_COLLECTOR_URL` — a **runtime** var) since `*.grafana.net` is ad-blocked. `nginx.conf.template` because nginx:alpine envsubsts `/etc/nginx/templates/`. Dockerfile defaults the collector to `http://127.0.0.1:1` so local compose starts.
- **`page_visits` is aggregate-only by design** — no id/IP/hash/session, because `/chcomms` promises no per-visitor tracking. Visits, never uniques. Ad-blocker-proof cross-check for RUM/GA.
- **GA4** (`frontend/src/lib/analytics.ts`, setup in `docs/ENV_SETUP.md`): loads **only on the production hostname, never under `navigator.webdriver`** (the prerender Chromium). **Visitor load speed outranks analytics**: gtag.js injects after `window.load` + `requestIdleCallback`; `page_view` waits for auth + schools fetch but capped at 3s (`GA_HOLD_MS`); nothing blocks rendering. Town/district come from the visitor's picked schools, not IP. Internal traffic via an in-browser `traffic_type=internal` flag (`?internal=1`, automatic for admins), not IP. GA sees `analyticsPath()` (only `utm_*` kept; tokens and personal/admin routes collapsed). **Focus never loads it**, and no child/student data goes into an event. Ads features and Google signals off; the Privacy page's per-device opt-out stands in for a consent banner — revisit if ads or identified analytics are added.

## Prod and deployment

Live at `https://schoolz.sitenaut.com` and `https://schoolz-api.sitenaut.com`.

- **The prod DB is the Supabase project misleadingly named `billz-prod`** (billz's real data is in the equally misnamed `clockin`). `DATABASE_URL` must be the **Session Pooler** on `aws-1-us-east-1` — the direct host is IPv6-only on the free tier (unreachable from GitHub runners); `aws-0` answers "tenant not found". RLS on with no policies is correct: nothing uses the Data API.
- **Custom domains must be Cloudflare DNS-only (grey cloud)**, or Fly certs never verify.
- **The scraper is on Fly's private network** (`http://schoolz-scraper.internal:8765`): 6PN is IPv6-only, so bind `::`; and it must **never auto-stop** — private traffic bypasses fly-proxy, so nothing wakes it and `.internal` resolves only started machines. It isn't in `deploy.yml`: ship with `fly deploy` from `scraper/`.
- **`schoolz-api` needs `--proxy-headers --forwarded-allow-ips='*'`** — Fly forwards plain HTTP, so `Location` headers came out `http://` and clients dropped POST bodies on the downgrade. `*` is safe; only fly-proxy reaches the port.
- **One-off prod scripts** run on the `scheduler` machine (always on), file under `/app`; the filesystem resets on deploy. Never run long scripts on an `app` machine over SSH — SSH doesn't count as traffic and it auto-stops mid-run. `fly ssh console` is intermittently unavailable; retry, don't diagnose.
- **Private preschools' documents/school-info/staff-roster scans are disabled** — chain websites, never one success, just burst load.
- **Prerender** (`/prerender`, for crawlers) is single-flighted per path, and serves stale cache if a re-render fails.
- **Supabase auth**: email signup requires the confirmation click first (reads as "login broken"). Google SSO needs the client ID/secret in Supabase *and* the Supabase callback in the client's redirect URIs.

### CI/CD — read this before assuming a merge shipped anything

- `migrate.yml` runs Alembic against prod on push to `main`, **only if the push touches `backend/alembic/**` or `backend/models.py`**.
- `deploy.yml` does **not** trigger on push — only via `workflow_run` after migrate, or manual dispatch.
- **So a merge touching neither path runs neither workflow.** Deploy: `gh workflow run deploy.yml -f target=both`; check `gh run list --branch main`. Full procedure in `.claude/skills/deploy-schoolz/SKILL.md`.
- `.woodpecker.yml` is supplementary self-hosted CI (test/build only).

## Testing

- **Run backend tests inside Docker, never on the host** (no guaranteed Python/pytest there). `backend/` is bind-mounted into `schoolz-api-local`, so edits are live; same container for `alembic upgrade head`.
- **pytest never writes to the shared local DB**: `conftest.py`'s autouse `_isolated_db_transaction` wraps each test in a rolled-back transaction (`join_transaction_mode="create_savepoint"`, `database.SessionLocal` monkeypatched). A helper doing `from database import SessionLocal` bypasses the patch and leaks rows — use `import database; database.SessionLocal()`.
- **Known flake**: `test_account.py::test_delete_account_requires_confirmation_and_password` occasionally 401s (PyJWT rejects a future `iat` if the container clock steps back). Re-run.

## Bugs whose mechanism is worth remembering

Silent ones — no error, no log line — that cost real time. (Source-specific ones live with their source above.)

- **Supabase auth deadlock.** `AuthContext` called `supabase.auth.getSession()` inside `onAuthStateChange`, which supabase-js invokes *while holding its auth lock*; `apiFetch` took the same lock, so requests queued until reload. RUM symptom: fetch batches stalling tens of seconds and unblocking on the same millisecond while the backend answered in under a second. **Never call a supabase auth method from that callback** — use the session it hands you. The token is cached in `api.ts` with one 401 replay; the route gate offers Reload after 8s.
- **`.gitignore` had a bare `lib/`** (Python boilerplate) that excluded `frontend/src/lib/`. Local builds passed; CI's fresh checkout failed.
