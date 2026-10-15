# Base images are pinned by version and digest; Dependabot proposes the
# bumps. Node matches CI (.github/workflows/ci.yml).
FROM node:22.23.3-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build
WORKDIR /app

ARG VITE_AUTH_MODE=local
ARG VITE_SUPABASE_URL=
ARG VITE_SUPABASE_PUBLISHABLE_KEY=
ARG VITE_API_URL=http://localhost:8000
ARG VITE_APP_VERSION=dev
# Empty by default (RUM off - src/lib/telemetry.ts no-ops with no URL). Prod
# sets this to "/rum/collect", the same-origin nginx proxy path defined
# below - never the real Grafana collector URL directly, so ad-blockers
# that flag *.grafana.net don't silently drop RUM data.
ARG VITE_FARO_URL=
# GA4 Measurement ID (public). Empty = analytics off (src/lib/analytics.ts).
ARG VITE_GA_MEASUREMENT_ID=
# The site's real public origin (src/lib/site.ts) - matches the backend's
# own PUBLIC_WEB_URL. Needed so canonical/Open Graph tags are still
# correct when the backend's prerender service renders a page via an
# internal-only URL (see nginx.conf.template + backend/services/prerender.py).
ARG VITE_PUBLIC_WEB_URL=http://localhost:5173
# Cloudflare Turnstile site key for the /upload bot check (public). Empty =
# no widget (src/components/BotCheck.tsx).
ARG VITE_TURNSTILE_SITE_KEY=
ENV VITE_AUTH_MODE=$VITE_AUTH_MODE \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY \
    VITE_API_URL=$VITE_API_URL \
    VITE_APP_VERSION=$VITE_APP_VERSION \
    VITE_FARO_URL=$VITE_FARO_URL \
    VITE_GA_MEASUREMENT_ID=$VITE_GA_MEASUREMENT_ID \
    VITE_PUBLIC_WEB_URL=$VITE_PUBLIC_WEB_URL \
    VITE_TURNSTILE_SITE_KEY=$VITE_TURNSTILE_SITE_KEY

# npm ci installs exactly the lockfile, or fails if it disagrees with
# package.json.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# The Focus app (focus/) - a separate Vite build served from the SAME
# ORIGIN at /focus/, which is what lets it share the auth session (see
# focus/README.md). It lives inside this directory rather than beside it
# because fly deploys with this directory as the Docker build context; a
# sibling would be invisible here. Shares the API/auth build args above so
# both apps point at the same backend in the same auth mode.
FROM node:22.23.3-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build-focus
WORKDIR /app
ARG VITE_AUTH_MODE=local
ARG VITE_API_URL=http://localhost:8000
ARG VITE_SUPABASE_URL=
ARG VITE_SUPABASE_PUBLISHABLE_KEY=
ENV VITE_AUTH_MODE=$VITE_AUTH_MODE \
    VITE_API_URL=$VITE_API_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY
COPY focus/package.json focus/package-lock.json ./
RUN npm ci
COPY focus/ .
RUN npm run build

# nginx-unprivileged runs as uid 101 with its pid file and caches in /tmp;
# it listens on 3000 (nginx.conf.template), which needs no root either.
FROM nginxinc/nginx-unprivileged:1.31.7-alpine@sha256:378d0c32f6562f7fd9629170797f57d2b953aa09be983b3daaf4809bb039ca00
COPY --from=build /app/dist /usr/share/nginx/html
# Must land exactly where nginx.conf.template's `location /focus/` looks,
# or that block's try_files fallback loops on a missing index.html and
# nginx answers 500 - which is what prod did between the block shipping
# and this stage existing.
COPY --from=build-focus /app/dist /usr/share/nginx/html/focus
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY security-headers.inc.template /etc/nginx/templates/security-headers.inc.template
# What the Content-Security-Policy lets the page connect to besides itself,
# and where browsers send violation reports. Local defaults; frontend/fly.toml
# sets prod's.
ENV CSP_CONNECT_SRC="http://localhost:8000" \
    CSP_REPORT_URL="/csp-report"
# Syntactically-valid placeholder so nginx's envsubst-on-templates startup
# step never produces a broken "proxy_pass ;" when FARO_COLLECTOR_URL isn't
# set (e.g. local compose, where RUM is off and VITE_FARO_URL is empty too)
# - fly secrets set -a schoolz-web FARO_COLLECTOR_URL=... overrides it in prod.
ENV FARO_COLLECTOR_URL=http://127.0.0.1:1
# Same reasoning as FARO_COLLECTOR_URL above: a syntactically-valid
# placeholder so envsubst never emits a broken "proxy_pass ;" if this
# isn't set. Local compose overrides it to http://backend:8000; prod's
# schoolz-web sets it to schoolz-api's public hostname (see
# frontend/fly.toml for why it's the public URL, not an internal one).
ENV BACKEND_INTERNAL_URL=http://127.0.0.1:1
# Docker Engine's embedded DNS server - correct default for local compose.
# Fly overrides this to its own system resolver (see frontend/fly.toml).
ENV RESOLVER=127.0.0.11
EXPOSE 3000

# For the local stack; on Fly the http_service checks in fly.toml count.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
