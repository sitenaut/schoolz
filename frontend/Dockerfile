FROM node:20-alpine AS build
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
ENV VITE_AUTH_MODE=$VITE_AUTH_MODE \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY \
    VITE_API_URL=$VITE_API_URL \
    VITE_APP_VERSION=$VITE_APP_VERSION \
    VITE_FARO_URL=$VITE_FARO_URL

COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# Syntactically-valid placeholder so nginx's envsubst-on-templates startup
# step never produces a broken "proxy_pass ;" when FARO_COLLECTOR_URL isn't
# set (e.g. local compose, where RUM is off and VITE_FARO_URL is empty too)
# - fly secrets set -a schoolz-web FARO_COLLECTOR_URL=... overrides it in prod.
ENV FARO_COLLECTOR_URL=http://127.0.0.1:1
EXPOSE 3000
