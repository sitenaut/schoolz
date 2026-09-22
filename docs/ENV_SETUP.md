# Environment setup

schoolz has two environments: **local** (docker compose, local Postgres, local
username/password auth) and **prod** (Fly.io, managed Postgres, Supabase auth
with Google SSO + email/password).

The whole `env/` directory is gitignored (see `.gitignore`) — nothing in it is
ever committed, including `.example` files, because some of these files hold
real secrets. This doc is the source of truth for what to create by hand.

Create `env/` at the repo root with these files:

## env/base.env
Shared, non-secret defaults.
```
DATABASE_NAME=schoolz
DATABASE_USER=schoolz
PUBLIC_WEB_URL=http://localhost:5173   # prod: https://schoolz-web.fly.dev (or custom domain)
PUBLIC_API_URL=http://localhost:8000   # prod: https://schoolz-api.fly.dev - used to build the Gmail OAuth redirect URI
```

## env/auth.local.env
```
AUTH_MODE=local
```

## env/auth.supabase-prod.env
```
AUTH_MODE=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_JWT_AUDIENCE=authenticated
BOOTSTRAP_ADMIN_EMAIL=you@example.com   # this email becomes admin on first Supabase login
```

## env/db.local.env
```
POSTGRES_PASSWORD=<pick-anything-locally>
```

## env/db.prod.env
```
DATABASE_URL=postgresql://...           # from your managed Postgres provider
DATABASE_SSL_MODE=require
```

## env/frontend.local.env
```
VITE_API_URL=http://localhost:8000
VITE_AUTH_MODE=local
```

## env/frontend.prod.env
Not used directly by compose — prod frontend env is baked in at build time via
`frontend/fly.toml`'s `[build.args]` (the Supabase URL/publishable key there
are meant to be public). Keep this file only if you want a local record of
what those build args should be.

## env/secrets.local.env
```
JWT_SECRET=<any long random string, local-only>
GRAFANA_PASSWORD=<admin password for the local Grafana UI>

# Optional: seeds a default admin user on backend startup (local auth mode
# only, idempotent - skipped if a user with this email/username already
# exists). Leave any of the three unset to skip seeding entirely.
ADMIN_EMAIL=admin@example.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<a real password, min 8 chars>

# Shared secret between backend and the scraper service (any random string).
SCRAPER_API_KEY=<any long random string>

# Local events (/local) scrape JS-heavy sites through the billz Playwright
# droplet first (stealth + extra waits), falling back to the scraper above.
# The key is billz's RECIPE_SCRAPER_KEY. Leave it unset to use only the local
# scraper; URL defaults to https://scraper-droplet.profitnaut.com.
LOCAL_EVENTS_SCRAPER_KEY=
LOCAL_EVENTS_SCRAPER_URL=

# Gmail OAuth (for the email parser - "Connect Gmail" on /gmail). NOT needed
# for Smore newsletter scanning (/smore), which needs no Google credentials
# at all. See notes/prod-checklist.md for how to create these in Google
# Cloud Console; register <PUBLIC_API_URL>/gmail/callback as the redirect URI.
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# For the Smore image-block vision-extraction pass. Plumbed through to both
# backend and scheduler containers, but not yet used anywhere - that pass
# isn't built yet (see CLAUDE.md).
ANTHROPIC_API_KEY=
```

## env/secrets.prod.env
Real secrets. In CI, this file is *materialized* from GitHub Actions
environment secrets (see `.github/workflows/migrate.yml`) — you generally
don't need to hand-create it except for a one-off local run against prod.
```
DATABASE_URL=postgresql://...
SUPABASE_SERVICE_ROLE_KEY=<service_role key - server-side only, never in the frontend>
# ^ also needed as a Fly secret on schoolz-api: DELETE /auth/me uses it to
#   remove the Supabase Auth identity along with the local user row. Without
#   it the local row is still deleted (the deletion is logged as partial).
```

## Running locally

```
cp .env.example .env   # optional, for ad hoc `docker compose` without the wrapper script
./scripts/compose-local.sh up --build
```

## Observability (local: metrics only so far; prod: not yet enabled)

Backend/scheduler push OpenTelemetry metrics via OTLP/HTTP. Locally, Alloy
receives that OTLP push (`alloy/config.alloy`, port 4318) and forwards to
Mimir; logs still go Promtail → Loki as before. Off by default; turn on with:

```
OBSERVABILITY=1 ./scripts/compose-local.sh up --build
```

That sets `OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318` plus
`OTEL_TRACES_EXPORTER=none`/`OTEL_LOGS_EXPORTER=none` (no local Tempo/Loki-via-OTLP
yet, so traces/logs aren't pushed locally — only metrics).

Grafana: http://localhost:3001 (login `admin` / `env/secrets.local.env`'s
`GRAFANA_PASSWORD`, or browse anonymously — anonymous admin access is enabled
for local convenience only, never do this in prod). Datasources and a starter
"schoolz backend overview" dashboard are auto-provisioned from `grafana/provisioning/`.

**Prod (Grafana Cloud)**: endpoint/token already live in `env/secrets.prod.env`
(`OTEL_EXPORTER_OTLP_ENDPOINT`, `SCHOOLZ_OTLP_TOKEN`) but not yet pushed to
Fly via `fly secrets set` — that step, plus the Faro (RUM) frontend wiring,
the `grafana_ro` read-only Postgres datasource, and Grafana dashboards/alerts,
are tracked phase-by-phase in `docs/OBSERVABILITY_PLAN.md`.

`scripts/compose-local.sh` sources `env/base.env`, `env/auth.local.env`,
`env/db.local.env`, `env/frontend.local.env`, `env/secrets.local.env` (in that
order — later files win) and then runs
`docker compose -f docker-compose.yml -f docker-compose.local.yml`.

## Running Alembic against an environment

```
scripts/alembic_env.sh local revision --autogenerate -m "..."
scripts/alembic_env.sh prod upgrade head
```
