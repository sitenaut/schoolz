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
```

## Running locally

```
cp .env.example .env   # optional, for ad hoc `docker compose` without the wrapper script
./scripts/compose-local.sh up --build
```

## Observability (optional, local only for now)

Metrics (Prometheus via Alloy → Mimir) and logs (Promtail → Loki), viewable in
Grafana. Off by default; turn on with:

```
OBSERVABILITY=1 ./scripts/compose-local.sh up --build
```

Grafana: http://localhost:3001 (login `admin` / `env/secrets.local.env`'s
`GRAFANA_PASSWORD`, or browse anonymously — anonymous admin access is enabled
for local convenience only, never do this in prod). Datasources and a starter
"schoolz backend overview" dashboard are auto-provisioned from `grafana/provisioning/`.

Not wired up for prod yet — see `notes/prod-checklist.md`.

`scripts/compose-local.sh` sources `env/base.env`, `env/auth.local.env`,
`env/db.local.env`, `env/frontend.local.env`, `env/secrets.local.env` (in that
order — later files win) and then runs
`docker compose -f docker-compose.yml -f docker-compose.local.yml`.

## Running Alembic against an environment

```
scripts/alembic_env.sh local revision --autogenerate -m "..."
scripts/alembic_env.sh prod upgrade head
```
