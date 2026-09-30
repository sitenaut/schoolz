#!/usr/bin/env bash
# Call the schoolz API with an admin API key (Admin → API keys), so a script
# or agent can seed and manage config without a browser login.
#
#   scripts/schoolz-api.sh prod GET  /auth/me
#   scripts/schoolz-api.sh prod POST /admin/config/import backend/seed/local_events.json
#   scripts/schoolz-api.sh local PATCH /scheduled-jobs/<id> body.json
#
# Keys live in env/api-keys.env (gitignored with the rest of env/):
#   SCHOOLZ_API_KEY_PROD=szk_...
#   SCHOOLZ_API_KEY_LOCAL=szk_...
# The key is handed to curl as a config file descriptor, so it never
# shows up in argv, `ps`, or this script's output.
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "usage: $0 <prod|local> <METHOD> <PATH> [BODY_FILE|-]" >&2
  exit 2
fi

target=$1 method=$2 path=$3 body=${4:-}
root=$(cd "$(dirname "$0")/.." && pwd)
keys_file="$root/env/api-keys.env"

case "$target" in
  prod)  base_url=${SCHOOLZ_API_URL_PROD:-https://schoolz-api.sitenaut.com}; var=SCHOOLZ_API_KEY_PROD ;;
  local) base_url=${SCHOOLZ_API_URL_LOCAL:-http://localhost:8000};        var=SCHOOLZ_API_KEY_LOCAL ;;
  *) echo "target must be prod or local" >&2; exit 2 ;;
esac

if [ -z "${!var:-}" ] && [ -f "$keys_file" ]; then
  # shellcheck disable=SC1090
  set -a; . "$keys_file"; set +a
fi
if [ -z "${!var:-}" ]; then
  echo "$var is not set (add it to env/api-keys.env - create a key in Admin → API keys)" >&2
  exit 2
fi

args=(-sS -X "$method" -w '\nHTTP %{http_code}\n')
if [ -n "$body" ]; then
  args+=(-H 'Content-Type: application/json' --data-binary "@$body")
fi
# The process substitution must sit on curl's own command line: inside the
# array assignment above, its fd is closed before curl ever reads it.
curl "${args[@]}" -K <(printf 'header = "Authorization: Bearer %s"\n' "${!var}") "$base_url$path"
