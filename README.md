# schoolz

**One public, bookmarkable page per school.** schoolz pulls together the school-day information Cherry Hill Public Schools parents currently have to hunt for across a district website, each school's own site, Smore newsletters, and whatever a particular school happens to email out — bell schedules, lunch menus, the calendar, absence and busing procedures, after-school care, staff contacts — and presents it consistently, the same way, for every school.

It's free, open source, and built to be handed to a district: everything in this repo (the data model, the scans, the tests) is aimed at feeding clean, source-attributed data into a public tool a school district could adopt or point parents to directly. See `docs/DISTRICT_COMMUNICATION_REPORT.md` for the pitch aimed at a district, and `docs/DATA_GAPS.md` for the technical detail behind it.

Almost everything is public and needs no account — the point is "bookmark your kid's school page," not "log in to see anything." Registering is optional, only for linking your own kids so the app can add their schools automatically.

## Architecture

```
React (Vite/TS) frontend  →  FastAPI backend  →  Postgres
                                   │
                                   ├─ scheduler process (recurring scans: cron + Postgres advisory locks)
                                   └─ scraper service (Playwright/Chromium, generic fetch-html)
```

- **`backend/`** — FastAPI + SQLAlchemy (async) + Alembic. Dual auth mode: `local` (email/username/password, for local dev) or `supabase` (Google SSO + email/password, for prod).
- **`frontend/`** — Vite + React + TypeScript. No component framework beyond React itself; a small hand-rolled design system in `frontend/src/styles.css`.
- **`scheduler/`** (inside `backend/`) — a separate long-running process, not the API. Every recurring data source (school websites, Smore newsletters, the district calendar feed, lunch menus, transportation pages, etc.) is a `ScheduledJob` row with a cron expression; the scheduler reconciles against that table every 30 seconds, so adding or editing a job needs no restart. `GET /scheduled-jobs` (admin) and the `/jobs` page show every job's schedule, last result, and next run.
- **`scraper/`** — a standalone, deliberately generic Playwright service (`/fetch-html`, `/fetch-raw`). All site-specific parsing lives in `backend/services/*.py`, not here, so the scraper itself is reusable for any district's site.
- **`backend/mcp_server.py`** — an [MCP](https://modelcontextprotocol.io) server exposing schoolz's public data as tools for Claude/Gemini/ChatGPT, mounted directly into this same app at `/mcp`. See "Using schoolz from an AI assistant" below.
- Two environments only: **local** (Docker Compose, local Postgres, local auth) and **prod** (Fly.io, managed Postgres, Supabase auth). No dev/stage tier.

For the full data model and the story of how each data source was found and parsed (Finalsite site quirks, Smore's block structure, the district's ICS calendar feed, bell schedules, transportation, etc.), read `CLAUDE.md` at the repo root — it's the running log of everything this project has learned about its actual data sources, kept up to date as the project grows.

## Using schoolz from an AI assistant

schoolz's public data (schools, districts, the calendar, tracked Smore newsletters) is exposed as [MCP](https://modelcontextprotocol.io) tools at a single URL - no install, no API key:

```
https://schoolz-api.sitenaut.com/mcp
```

Add it as a remote MCP server / connector in Claude, Gemini, or ChatGPT and ask something like *"what's on the calendar for Bret Harte Elementary this week"* or *"does Chesterbrook have a lunch menu posted."* Exactly what a browser sees at [schoolz.sitenaut.com](https://schoolz.sitenaut.com) - nothing more, no login-gated data.

Two things worth knowing about how it behaves:

- **When something isn't tracked yet, the assistant is told to say so and suggest a fix** - ask the school to publish it, or hand schoolz a link to something that already covers it (a newsletter, a handbook, a flier). That's not a canned response; it's literally in the tool's result, aimed at the assistant relaying it to you.
- **There's a tool for submitting that link on the spot** (`submit_community_content`) - no login needed, but nothing goes live automatically; a schoolz admin reviews every submission first, same as filling out [schoolz.sitenaut.com/contact](https://schoolz.sitenaut.com/contact) by hand.

It's a thin, read-mostly layer over the same public API the website calls - see `backend/mcp_server.py` for the full tool list and how the advocacy-nudge wrapping works. Running it locally is just running the backend (`docker compose up backend`) and pointing your MCP client at `http://localhost:8000/mcp` instead.

## Running locally

Prerequisites: Docker, Docker Compose.

1. Create the `env/` directory at the repo root with the files described in **`docs/ENV_SETUP.md`** — that file is the source of truth for exactly what each one holds (none of `env/` is committed; some of it can hold real secrets). At minimum you need `env/base.env`, `env/auth.local.env`, `env/db.local.env`, `env/frontend.local.env`, `env/secrets.local.env`.
2. Start the stack:
   ```
   ./scripts/compose-local.sh up --build
   ```
   This runs Postgres, an Alembic migration step, the backend API, the scheduler, the scraper, and the frontend.
3. Open the frontend at **http://localhost:5173**. The backend API is at **http://localhost:8000** (`/health` for a quick check, `/docs` for the OpenAPI/Swagger UI).
4. First visit lands on a school picker (`/start`) — no account needed. If you set `ADMIN_EMAIL`/`ADMIN_USERNAME`/`ADMIN_PASSWORD` in `env/secrets.local.env`, that admin account is seeded on backend startup (idempotent) and can sign in via the "Sign in" button to reach an "Admin" section in the nav — newsletters (`/smore`), scheduled scans (`/jobs`), and config import/export (`/admin/config`, see below).

Optional local observability (Prometheus-style metrics + logs, viewable in Grafana):
```
OBSERVABILITY=1 ./scripts/compose-local.sh up --build
```
Grafana at http://localhost:3001. Not wired up for prod.

### Running tests

```
cd backend && pytest -q
cd frontend && npm run build && npm run test
```

The backend test suite runs against the same Postgres as the dev stack (not a separate test database), but each test is wrapped in its own transaction that's rolled back afterward, so nothing it creates persists — safe to run repeatedly with no manual cleanup. (If you're on a database with leftover rows from before this existed, `python backend/scripts/cleanup_test_data.py` sweeps them once; see `CLAUDE.md` for the story.)

### Database migrations

Schema changes go through Alembic, targeting either environment:
```
./scripts/alembic_env.sh local revision --autogenerate -m "..."
./scripts/alembic_env.sh local upgrade head
./scripts/alembic_env.sh prod upgrade head
```

## Deploying to production

Production is two Fly.io apps (`schoolz-api`, `schoolz-web`) plus a managed Postgres and a Supabase project for auth. This is a from-scratch checklist for anyone standing up their own instance (a fork, or a district's own deployment) — nothing here assumes you have access to the original author's infrastructure.

### 1. Supabase (auth)
- Create a Supabase project.
- Enable the **Email** provider (with confirmations) and **Google** as an auth provider.
- For Google: create an OAuth client in Google Cloud Console, set its authorized redirect URI to `https://<your-supabase-project-ref>.supabase.co/auth/v1/callback`, and paste the client ID/secret into Supabase's Google provider settings.
- Under Auth settings, set the Site URL / Redirect URLs to your prod frontend origin (e.g. `https://schoolz-web.fly.dev`, or your custom domain once you have one).
- You'll need the project's URL and **publishable (anon) key** — these are safe to bake into the public frontend build (see step 4). Never put the **service_role** key anywhere client-side; it only belongs in backend secrets.

### 2. Database
- Provision a managed Postgres instance (Fly Postgres, Supabase's own Postgres product, or any other managed provider).
- Set `DATABASE_URL` (and `DATABASE_SSL_MODE=require` if your provider needs it) as a secret for both the migration step and the backend app.
- Run `./scripts/alembic_env.sh prod upgrade head` once by hand to confirm connectivity before wiring up CI.

### 3. Fly.io apps
- `fly apps create schoolz-api` and `fly apps create schoolz-web` (or your own app names — update the `app =` line in both `backend/fly.toml` and `frontend/fly.toml` if so).
- Generate a deploy token (`fly tokens create deploy`) and store it as a `FLY_API_TOKEN` secret in whatever CI you use (see step 6).
- Fill in the real Supabase URL and publishable key in `frontend/fly.toml`'s `[build.args]` — these are baked into the static frontend bundle at build time, since it's a client-side app with no server to read env vars from at runtime.
- Set backend secrets on Fly (`fly secrets set -a schoolz-api DATABASE_URL=... JWT_SECRET=... SUPABASE_JWT_AUDIENCE=... BOOTSTRAP_ADMIN_EMAIL=... SUPABASE_SERVICE_ROLE_KEY=... ANTHROPIC_API_KEY=... GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... SCRAPER_URL=... SCRAPER_API_KEY=...`, whichever you're actually using — `backend/fly.toml` also runs the `scheduler` process group, so these secrets are shared by both).
- First deploy manually from each of `backend/` and `frontend/` (`fly deploy`) to confirm both apps boot before relying on CI.

### 4. The scraper service
The scraper (`scraper/`) is a long-running headless-Chromium process, which doesn't fit Fly's scale-to-zero model well. It needs a host that stays up: a small VM/droplet, a container platform, or any place you can run `docker build`/`docker run` against `scraper/`'s Dockerfile continuously. Point the backend and scheduler at it via `SCRAPER_URL` + a shared `SCRAPER_API_KEY` (sent as an `X-API-Key` header). It has no district-specific logic in it at all — every site's parsing rules live in `backend/services/`, so the same scraper instance works for any district you point this project at.

### 5. CI/CD (optional, but this repo ships workflows for it)
- **`.github/workflows/migrate.yml`** — runs Alembic against prod on a push to `main` that touches `backend/alembic/**` or `backend/models.py`, or on manual dispatch. It materializes `env/secrets.prod.env` from GitHub Actions environment secrets, so you'll want a `prod` GitHub environment with `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and anything else `backend/services/database.py` needs.
- **`.github/workflows/deploy.yml`** — deploys the backend, then the frontend, triggered after a successful migrate run (or manually). Needs `FLY_API_TOKEN`.
- **`.woodpecker.yml`** — a supplementary self-hosted CI config (test/build only, no deploy) if you run your own Woodpecker server; unnecessary if you're relying on GitHub Actions alone.

### 6. Gmail OAuth (optional — only needed for the personal email-scanner feature)
Most of this app needs no Google credentials at all — Smore newsletter scanning, the district calendar feed, lunch menus, transportation, and every other public-data scan are plain HTTP fetches. Gmail OAuth is only for the opt-in "connect your Gmail" feature that lets an individual guardian auto-detect school emails in their own inbox.
- Create a separate Google Cloud project + OAuth 2.0 Client ID, enable the Gmail API, and request only the `gmail.readonly` scope (this feature never sends, deletes, or modifies mail).
- Authorized redirect URI: `<your prod API URL>/gmail/callback`, matching exactly.
- Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` as backend secrets.

### 7. Anthropic API key (optional — only needed for newsletter content extraction)
Turning a Smore newsletter's raw blocks into structured events/deadlines/announcements uses Claude (vision for flyer images, then a structured tool-use call). Set `ANTHROPIC_API_KEY` as a backend secret if you want this; without it, Smore blocks are still fetched and stored, just not turned into calendar items automatically.

## Porting configuration to a new environment (e.g. local → prod)

Everything an admin sets up — tracked schools, districts, Smore newsletter links, bell schedules, SACC info, and every recurring scan those imply — can be exported from one environment and imported into another with one script, so a fresh prod database doesn't mean re-entering all of it by hand:

```
cd backend
python scripts/migrate_config.py \
  --source-url http://localhost:8000 --source-user <admin> --source-password <...> \
  --target-url https://schoolz-api.fly.dev --target-user <admin> --target-password <...>
```

There's also a UI for this — sign in as an admin and look for **Import/export** under the "Admin" section of the nav (bottom bar on mobile, left rail on desktop; `/admin/config` directly). It exports a downloadable JSON file and imports one back (paste it or choose the file), showing the same created/updated counts. The CLI script above is the same thing without needing a browser open on both environments — both are thin clients for two admin-only endpoints, `GET /admin/config/export` and `POST /admin/config/import` (`backend/routers/admin_config.py`), which never touch either database directly. Import goes through the exact same job-creation logic as the normal admin UI (setting a district's transportation URL still creates its `transportation.scan` job, a school's `website_url` still creates its staff-roster/documents/school-info jobs), so nothing about the imported data behaves differently from having entered it by hand. It's scoped to centrally-managed, already-public configuration only — never user accounts, linked students, or Gmail connections, which are personal to each environment.

It's idempotent (matched by district name, school slug, and newsletter URL), so it's safe to re-run after making more changes locally — a second run only touches what's different, and reports exactly how many rows were created vs. updated:

```
Import result:
  districts_created: 0
  districts_updated: 1
  schools_created: 28
  schools_updated: 0
  smore_created: 8
  smore_updated: 0
  smore_skipped: []
  sacc_created: 12
  sacc_updated: 0
```

Useful variations:
```
# Inspect what would be exported, save it to a file, without importing anywhere:
python scripts/migrate_config.py --source-url http://localhost:8000 \
  --source-user <admin> --source-password <...> --dry-run --out export.json

# Import a previously-saved file instead of pulling live from a source:
python scripts/migrate_config.py --in export.json \
  --target-url https://schoolz-api.fly.dev --target-user <admin> --target-password <...>
```

Once the recurring scans this creates have run in prod at least once, everything that's *discovered* rather than admin-entered (staff directories, documents, lunch menus, calendar events, extracted newsletter content) will populate on its own — there's no need to port that part, only the configuration that makes those scans exist.

## What's here vs. what's next

This app deliberately covers the two kinds of information every parent needs on a regular basis and that don't involve any student-specific data: **school processes and procedures** (bell schedules, lunch, absences, busing, after-school care) and **district/school events, initiatives, and deadlines**. It stays out of the third category — a child's actual educational world (assignments, teacher communication, grades) — on purpose: that data is sensitive, belongs behind real authentication and district policy, and the better near-term fix is almost certainly the district enabling parent access to Google Classroom with its existing privacy safeguards, not another app collecting more of it. See `docs/DISTRICT_COMMUNICATION_REPORT.md` for that argument in full, aimed at a conversation with the district.

## License

Open source, offered as a free service to the Cherry Hill Public Schools community. (Add your preferred license file if you're forking this for another district — none is currently checked in.)
