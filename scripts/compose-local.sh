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

# Dump the local database before anything that recreates or removes containers
# (docs/BACKUPS.md). A failed dump only stops a command that would delete the
# volume; SCHOOLZ_SKIP_BACKUP=1 turns this off.
if [ "${SCHOOLZ_SKIP_BACKUP:-0}" != "1" ]; then
  backup_when=""
  for arg in "$@"; do
    case "$arg" in
      up|rm) [ -n "$backup_when" ] || backup_when=stale ;;
      down) backup_when=down ;;
      -v|--volumes) [ "$backup_when" != down ] || backup_when=always ;;
    esac
  done
  case "$backup_when" in
    always)
      if ! bash "$ROOT_DIR/scripts/backup-local.sh"; then
        echo "Local database not backed up, and this command deletes its volume. Start Postgres and retry, or set SCHOOLZ_SKIP_BACKUP=1 to delete it anyway." >&2
        exit 1
      fi
      ;;
    stale|down)
      rc=0
      bash "$ROOT_DIR/scripts/backup-local.sh" --if-stale 2>/dev/null || rc=$?
      # 3 = Postgres is not running (first start, or already stopped).
      if [ "$rc" != 0 ] && [ "$rc" != 3 ]; then
        echo "Warning: local database backup failed - run  bash scripts/backup-local.sh  to see why." >&2
      fi
      ;;
  esac
fi

# The scraper service builds from the shared playwright-scraper checkout.
# Offline or without access to that repo, everything else still runs.
if ! bash "$ROOT_DIR/scripts/scraper-source.sh" >/dev/null; then
  echo "Warning: couldn't check out playwright-scraper (scripts/scraper-source.sh); the scraper service won't build." >&2
fi

cd "$ROOT_DIR"
exec "${run_prefix[@]}" docker compose -f docker-compose.yml -f docker-compose.local.yml "$@"
