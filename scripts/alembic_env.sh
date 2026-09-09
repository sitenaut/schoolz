#!/usr/bin/env bash
# Run an Alembic command against a given environment's database.
#
# Usage: scripts/alembic_env.sh <local|prod> <alembic-args...>
# Example: scripts/alembic_env.sh prod upgrade head
#
# Expects env/base.env, env/db.<env>.env and (for prod) env/secrets.<env>.env
# to already exist locally (see docs/ENV_SETUP.md) or to have been
# materialized by CI from GitHub Actions secrets.
set -euo pipefail

ENVIRONMENT="${1:?usage: alembic_env.sh <local|prod> <alembic-args...>}"
shift

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT_DIR/env"

case "$ENVIRONMENT" in
  local|prod) ;;
  *) echo "Unknown environment: $ENVIRONMENT (expected local or prod)" >&2; exit 1 ;;
esac

set -a
# shellcheck disable=SC1091
[ -f "$ENV_DIR/base.env" ] && source "$ENV_DIR/base.env"
# shellcheck disable=SC1091
[ -f "$ENV_DIR/db.$ENVIRONMENT.env" ] && source "$ENV_DIR/db.$ENVIRONMENT.env"
# shellcheck disable=SC1091
[ -f "$ENV_DIR/secrets.$ENVIRONMENT.env" ] && source "$ENV_DIR/secrets.$ENVIRONMENT.env"
set +a

export APP_ENV="$ENVIRONMENT"

cd "$ROOT_DIR/backend"
exec /tmp/schoolz-venv/bin/alembic "$@"
