#!/usr/bin/env bash
# Run docker compose for local dev with the layered env/ files sourced in.
#
# Usage: scripts/compose-local.sh up --build
# Add observability (Grafana/Mimir/Loki/Promtail): OBSERVABILITY=1 scripts/compose-local.sh up --build
# Add the scheduler (off by default - see docker-compose.yml): SCHEDULER=1 scripts/compose-local.sh up --build
#
# Secrets come from 1Password: compose runs under `op run` with the references
# in env.op/secrets.local.env, so they never sit in a file. Sign in first with
# `eval $(op signin)`. SCHOOLZ_SECRETS=file falls back to the plain
# env/db.local.env + env/secrets.local.env (transition only).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT_DIR/env"

env_files=(base.env auth.local.env frontend.local.env)
run_prefix=()
if [ "${SCHOOLZ_SECRETS:-op}" = "file" ]; then
  env_files+=(db.local.env secrets.local.env)
else
  if ! command -v op >/dev/null; then
    echo "1Password CLI (op) not found - see docs/ENV_SETUP.md, or set SCHOOLZ_SECRETS=file." >&2
    exit 1
  fi
  # Unattended (agent sessions, phone): a read-only service account scoped to
  # the schoolz-local vault, its token kept outside the repo and OneDrive.
  token_file="${SCHOOLZ_OP_TOKEN_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/schoolz/op-local-token}"
  if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ] && [ -r "$token_file" ]; then
    OP_SERVICE_ACCOUNT_TOKEN="$(<"$token_file")"
    export OP_SERVICE_ACCOUNT_TOKEN
  fi
  if ! op whoami >/dev/null 2>&1; then
    echo "Not signed in to 1Password: set up the local service account (docs/ENV_SETUP.md) or run  eval \$(op signin)  and retry." >&2
    exit 1
  fi
  run_prefix=(op run --env-file "$ROOT_DIR/env.op/secrets.local.env" --)
fi

for f in "${env_files[@]}"; do
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
# Pin the project name: compose derives it from the directory, so a git worktree
# would start a second stack that collides with the running one's container names.
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-schoolz}"
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
exec "${run_prefix[@]}" docker compose -f docker-compose.yml -f docker-compose.local.yml "$@"
