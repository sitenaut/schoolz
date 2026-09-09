#!/usr/bin/env bash
# Run docker compose for local dev with the layered env/ files sourced in.
#
# Usage: scripts/compose-local.sh up --build
# Add observability (Grafana/Mimir/Loki/Promtail): OBSERVABILITY=1 scripts/compose-local.sh up --build
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
if [ "${OBSERVABILITY:-0}" = "1" ]; then
  export COMPOSE_PROFILES=obs-local
fi

cd "$ROOT_DIR"
exec docker compose -f docker-compose.yml -f docker-compose.local.yml "$@"
