# CLAUDE.md

Guidance for Claude Code working in this repository.

**What belongs here:** decisions and their rationale, non-obvious constraints, and bugs whose mechanism would cost real time to rediscover. **What doesn't:** anything derivable from the code, per-school data (that lives in the database), coverage counts, or traffic numbers (those live in Grafana and are stale the moment they're written). Dates are in git; don't date entries. Subsystem detail too long for every session goes in `docs/` with a pointer here. Area-specific detail lives next to its area, not here — see "Where the rest lives"; add new notes there and keep only a one-line tripwire in this file.

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

**Secret values live in 1Password** (`schoolz-local`/`-prod`/`-ci` vaults), not in files. `compose-local.sh` injects them with `op run` from the committed `env.op/secrets.local.env`. The `op` sign-in lives in the owner's own shell, so an agent's shell isn't signed in and `compose-local.sh` fails there: ask the owner to run it, and use `docker exec` on the running containers yourself. Never print a secret value; refer to secrets by name.

**Admin bootstrap:** locally, `ADMIN_EMAIL`/`ADMIN_USERNAME`/`ADMIN_PASSWORD` (in the `schoolz-local` vault) seed an admin on startup (idempotent, local auth only — `auth.py:seed_admin`). Prod's equivalent is `BOOTSTRAP_ADMIN_EMAIL`, which flags a Supabase email as admin on first login.

## Access model: public by default

Deliberate product pivot: **almost everything is public, no account needed.** The target workflow is "bookmark your kid's school page," not "log in to see anything." Registering is optional, only for the personal layer (your own kids, a narrowed calendar). Enforced in `backend/auth.py` + per-router:

- **Public** — every `GET` on schools/districts/calendar/newsletters/local events/directory. `GET /calendar` uses `get_optional_user` (returns `None` rather than 401) so it *degrades*: a logged-in guardian gets it narrowed to their schools, an anonymous visitor sees everything. An explicit `school_id` narrows either way.
- **Authenticated** — students, guardian links, invites, notifications, account settings. Registering never grants admin.
- **Admin** — creating/editing District/School/SmoreNewsletter, any `run-now`, `/scheduled-jobs`, and Gmail connection + email scanners (connecting an inbox is data-source management, not a guardian task). Scanner rows stay owner-scoped so two admins don't see each other's captures.
  - `User.is_admin` means **super admin**: every permission, and the only tier that can manage users/roles (`require_super_admin`, `routers/admin_users.py`). Nobody can remove their own super admin, which guarantees one remains.
  - Everyone else gets admin access through **`Role`s**, each a set of keys from the fixed catalog in `backend/permissions.py`. Permissions live in code because real endpoints must check each one; roles are data. Read/write pairs where an area has admin-only reads (`x.manage` implies `x.view` via `permissions.expand`): GETs check `.view`, mutations `.manage`, via `require_permission("<key>")` (a cached factory, so tests override a gate by identity). `/auth/me` returns `permissions` for the UI (`lib/permissions.ts`, `AdminLayout` tabs, `RequireAdmin permission=…`). Users/roles management is deliberately not grantable, so no role can mint admins. Scoping is by *function*, not by school/district. Roles take effect on the next request (no token claims).
- **API keys** (`ApiKey`, `routers/admin_api_keys.py`) — so a script or agent can change prod, where `/auth/login` can't be scripted (Supabase-only). A key acts as its creator narrowed to the permissions ticked (intersected at request time, so demoting the creator shrinks the key) and **never passes `require_super_admin`**, so no key can manage users, roles or keys. `szk_` prefix, only the SHA-256 stored, optional expiry; requests log `api_key_id`.
  - Get one with **`scripts/schoolz-api.sh login prod`** (device flow, approved by a super admin in a browser; the key lands in gitignored `env/api-keys.env` and never passes through chat). Details: `docs/API_KEYS.md`.
  - **This is the sanctioned route for prod admin changes — never a direct DB connection.**

The chatbot (`POST /chat`) straddles the tiers: public tools for anonymous callers, personal read-only tools with the caller's own bearer token when signed in. See the `chatbot` skill.

## Domain model

**Students are shared, never owned.** A `Student` is the canonical record for a real child; each guardian has their own `GuardianStudentLink`. Deleting your link removes only *your* view.

- **Auto-matching** — `Student.match_key` = normalized `first_name|last_name|student_id`. A matching add links to the *same* Student with no approval gate, and every already-linked guardian gets a `guardian_matched` `Notification`, so it's never silent. The divorced-parents scenario (shared kids visible to both, non-shared kids private, one parent's delete doesn't affect the other) is covered in `tests/test_students.py`.
- **Guardian invites** (`routers/invites.py`) — per-child, token-based, 7-day expiry. The unauthenticated preview shows only first name + last initial, so an invite link can't be used to fish for a child's identity. The frontend preserves the target across register/login via `?next=`.
- **Student accounts** (`routers/student_accounts.py`) — `Student.user_id` points at the student's own `User`; the account *is* that pointer. Stricter than guardian invites: the logged-in email must match the invited one, one account per student, and a guardian of that student can't claim it. `bucket3._get_own_student` allows guardian **or** student, so both see identical data; `viewer_role` tells the UI which guardian-only controls to hide. Deleting a student's login nulls `Student.user_id`, never the student.
- **`Student.school_id` is required** and chosen from tracked schools, never free text.
- **Per-account vs per-student keying is a privacy decision.** A `Student` row is visible to every linked guardian, so anything that is one person's own preference is keyed on **`user_id`**, never `student_id`: `CourseDisplayPreference` (rename/recolor a class; follows the person across devices, invisible to other guardians), `ClassPaymentTick` (each guardian tracks their own "have I paid this"). Facts about the child are keyed per student so every guardian sees the same thing: `StudentSpecial` (which special — Art, PE, … — falls on each rotation day; typed in on My Children, since specials appear nowhere in captured Genesis pages). Late policies are per *(student, course)* — see below.

### Schools, districts, content

- **`District`** exists because some resources are published district-wide per school type (lunch menus are the confirmed case). `School.district_id` + `School.school_type` (`elementary|middle|high|alternative|other`) is what makes `GET /schools/{id}/lunch-menu` resolve automatically.
- **`School.slug`** is derived once at creation, never regenerated (a permalink, not a label). `routers/schools.py:resolve_school` resolves id **or** slug in one query.
- **`School.short_name`** — `derive_school_short_name()` strips type suffix and district prefix, but it can't tell a droppable middle initial from a real given name, so it's editable via `PATCH /schools/{id}`.

Content scoping (school vs district items, dedup) and high-school class pages are in the `content-extraction` skill.

## Where the rest lives

Detail that only matters inside one area is kept out of this file. **Load the matching skill before working in its area** — each holds silent-failure bugs you won't rediscover from the code. The one-liners below are tripwires, not the full story.

Loaded automatically when you read files in that directory:

- **`frontend/CLAUDE.md`** — Today feed, page order, shared filters, modals and the iOS keyboard, admin UI kit, UI reference template, verifying UI without a host browser, the Supabase auth deadlock.
- **`backend/scheduler/CLAUDE.md`** — registry/runner/entrypoint, result states, error codes, cadence, auto-scheduling.
  - The scheduler is **opt-in locally** (`SCHEDULER=1`): left on, it re-ran every scan from the home IP and got that network CAPTCHA'd. Test a scan with its run-now.
  - Build triggers with `runner.cron_trigger`, never `CronTrigger.from_crontab` (weekday numbering differs; weekly jobs fired a day late).
  - Changing an `_ensure_*_job` constant doesn't update existing rows.
  - Don't force-error a slow run-now on a hunch; check for real evidence.
  - `uvicorn --reload` watches `backend/` incl. `tests/`, so editing any file kills a run-now job in the API process. Run long jobs from `schoolz-scheduler-local`.

Skills (`.claude/skills/<name>/SKILL.md`):

- **`kids-view`** — Kids View, Focus prioritisation, late-work policies, teacher exceptions, points, help requests.
  - After any parser change, run **Re-read imported pages** (`POST .../bucket3/reprocess`); import dedups by content hash.
  - `late_credit()` returns `None` for "no policy on file" — never collapse it into zero; only a known zero may hide work.
- **`content-extraction`** — `content_extractor.py`, status titles, supersede/dedup, content scoping, class pages.
  - `items` must stay **first** in the tool schema, and a schema's `"required"` isn't enforced — always `item.get(...)`.
  - Half-day/closure wording lives in three places that must agree: `school_today.py`, `school_status.py`, `frontend/src/lib/districtItems.ts`.
- **`data-sources`** — per-source quirks for every scan (Smore, menu vendors, rosters, calendars, documents, weather).
  - Zero results is usually a silent source change, not "nothing new". Read the source's entry before debugging.
- **`onboard-district`** — agent-based crawl workflow (`.claude/agents/district-crawler.md`) and seed import mechanics. Read `docs/ONBOARDING_CRAWL_GUIDE.md` first, then only the matching `docs/platforms/` file; record gaps in `docs/DATA_GAPS.md`.
- **`chatbot`** — tools per tier, prompt caching, the four Anthropic keys, providers.
  - The anonymous prompt prefix is barely over Haiku 4.5's cache minimum — trimming it silently stops caching.
  - Anonymous and signed-in providers are switched separately on purpose (signed-in chats carry children's data).
- **`observability`** — OTel, Grafana rules/SLOs/IRM, Loki, Faro RUM, GA4, `page_visits`.
  - The Grafana notification policy tree is shared with billz and the scraper repo: never `PUT` a tree built from scratch.
  - If a panel goes blank, check which metric-name spelling prod emits first.
  - Analytics never blocks rendering, never loads in Focus, and never carries child data.
- **`deploy-schoolz`** — the deploy procedure plus prod facts (which Supabase project, pooler host, Fly networking, one-off scripts).

Docs:

- **`docs/LOCAL_EVENTS_SOURCES.md`** — `/local` community events (`backend/local_events/`, a port of billz's pipeline; public, no auth).
  - **Deleting a job, or removing a source from its params, deletes that source's events.** `prune.SOURCE_KEYS` must list every `*_sources` key.
- `docs/ENV_SETUP.md`, `docs/API_KEYS.md`, `docs/RUNBOOK.md` (one section per alert), `docs/KIDS_VIEW_V2_DESIGN.md`, `docs/HS_CLASS_PAGES_DESIGN.md`.

## Prod and deployment

Live at `https://schoolz.sitenaut.com` and `https://schoolz-api.sitenaut.com`. Prod admin changes go through `scripts/schoolz-api.sh`, never a direct DB connection.

**A merge may deploy nothing.** `migrate.yml` runs only when a push to `main` touches `backend/alembic/**` or `backend/models.py`, and `deploy.yml` runs only after migrate or by manual dispatch — so a merge touching neither path runs neither. Deploy with `gh workflow run deploy.yml -f target=both` and check `gh run list --branch main`. Procedure and prod facts: the `deploy-schoolz` skill.

## Testing

- **Run backend tests inside Docker, never on the host** (no guaranteed Python/pytest there). `backend/` is bind-mounted into `schoolz-api-local`, so edits are live; same container for `alembic upgrade head`.
- **pytest never writes to the shared local DB**: `conftest.py`'s autouse `_isolated_db_transaction` wraps each test in a rolled-back transaction (`join_transaction_mode="create_savepoint"`, `database.SessionLocal` monkeypatched). A helper doing `from database import SessionLocal` bypasses the patch and leaks rows — use `import database; database.SessionLocal()`.
- **Known flake**: `test_account.py::test_delete_account_requires_confirmation_and_password` occasionally 401s (PyJWT rejects a future `iat` if the container clock steps back). Re-run.

## Bugs whose mechanism is worth remembering

Silent ones — no error, no log line — that cost real time. (Area-specific ones live with their area.)

- **`.gitignore` had a bare `lib/`** (Python boilerplate) that excluded `frontend/src/lib/`. Local builds passed; CI's fresh checkout failed.
