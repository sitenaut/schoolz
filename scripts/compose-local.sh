#!/usr/bin/env bash
# Run docker compose for local dev with the layered env/ files sourced in.
#
# Usage: scripts/compose-local.sh up --build
# Add observability (Grafana/Mimir/Loki/Promtail): OBSERVABILITY=1 scripts/compose-local.sh up --build
# Add the scheduler (off by default - see docker-compose.yml): SCHEDULER=1 scripts/compose-local.sh up --build
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT_DIR/env"

for f in base.env auth.local.env db.local.env frontend.local.env secrets.local.env; do
  if [ ! -f "$ENV_DIR/$f" ]; then
    echo "Missing $ENV_DIR/$f — see docs/ENV_SETUP.md for what to put in it." >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_DIR/$f"
  set +a
done

export APP_ENV=local
export COMPOSE_DISABLE_ENV_FILE=1
profiles=()
if [ "${SCHEDULER:-0}" = "1" ]; then
  profiles+=(scheduler)
fi
if [ "${OBSERVABILITY:-0}" = "1" ]; then
  profiles+=(obs-local)
  # Send backend/scheduler traces+metrics+logs to the local Alloy OTLP
  # receiver instead of Grafana Cloud - traces/logs exporters off since
  # this local stack has no Tempo/Loki-via-OTLP wired up (Promtail still
  # ships stdout logs the old way).
  export OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318
  export OTEL_TRACES_EXPORTER=none
  export OTEL_LOGS_EXPORTER=none
fi

export COMPOSE_PROFILES="$(IFS=,; echo "${profiles[*]}")"

cd "$ROOT_DIR"
exec docker compose -f docker-compose.yml -f docker-compose.local.yml "$@"
