#!/usr/bin/env bash
# Call the schoolz API with an admin API key, so a script or agent can seed
# and manage config without a browser login.
#
#   scripts/schoolz-api.sh login prod [client name]    # get a key by approving on your phone
#   scripts/schoolz-api.sh prod GET  /auth/me
#   scripts/schoolz-api.sh prod POST /admin/config/import backend/seed/local_events.json
#   scripts/schoolz-api.sh local PATCH /scheduled-jobs/<id> body.json
#
# `login` is a device flow: it prints a short code and a link, a super admin
# opens the link (signed in, e.g. on a phone), checks the code and approves,
# and the script writes the key into env/api-keys.env itself. The key is
# never printed. Keys can also be made by hand in Admin → API keys and saved
# there as SCHOOLZ_API_KEY_PROD=szk_... / SCHOOLZ_API_KEY_LOCAL=szk_...
#
# The key is handed to curl as a config file descriptor, so it never shows
# up in argv, `ps`, or this script's output.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
keys_file=${SCHOOLZ_API_KEYS_FILE:-"$root/env/api-keys.env"}

resolve_target() {
  case "$1" in
    prod)
      base_url=${SCHOOLZ_API_URL_PROD:-https://schoolz-api.sitenaut.com}
      web_url=${SCHOOLZ_WEB_URL_PROD:-https://schoolz.sitenaut.com}
      var=SCHOOLZ_API_KEY_PROD ;;
    local)
      base_url=${SCHOOLZ_API_URL_LOCAL:-http://localhost:8000}
      web_url=${SCHOOLZ_WEB_URL_LOCAL:-http://localhost:5173}
      var=SCHOOLZ_API_KEY_LOCAL ;;
    *) echo "target must be prod or local" >&2; exit 2 ;;
  esac
}

if [ "${1:-}" = login ]; then
  [ $# -ge 2 ] || { echo "usage: $0 login <prod|local> [client name]" >&2; exit 2; }
  resolve_target "$2"
  client_name=${3:-"Claude Code on $(hostname)"}
  exec python3 - "$base_url" "$web_url" "$var" "$keys_file" "$client_name" <<'PY'
import json, os, re, sys, time, urllib.error, urllib.request

base_url, web_url, var, keys_file, client_name = sys.argv[1:6]

def post(path, body):
    req = urllib.request.Request(
        base_url + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"POST {path} failed: {exc.code} {exc.read().decode()[:300]}")

start = post("/auth/device/start", {"client_name": client_name[:100]})
code = start["user_code"]
print(f"Approve this login: {web_url}/admin/api-keys/approve?code={code}", flush=True)
print(f"Check the page shows the code {code}. Waiting up to {start['expires_in'] // 60} minutes...", flush=True)

deadline = time.time() + start["expires_in"]
while time.time() < deadline:
    time.sleep(start["interval"])
    got = post("/auth/device/token", {"device_code": start["device_code"]})
    if got["status"] == "pending":
        continue
    if got["status"] != "approved":
        sys.exit(f"Login {got['status']}.")
    os.makedirs(os.path.dirname(keys_file), exist_ok=True)
    lines = []
    if os.path.exists(keys_file):
        with open(keys_file) as f:
            lines = [l for l in f.read().splitlines() if not re.match(rf"\s*{var}\s*=", l)]
    lines.append(f"{var}={got['key']}")
    fd = os.open(keys_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(keys_file, 0o600)
    print(f"Approved. Saved {var} ({got['key_prefix']}...) to {keys_file} with: {', '.join(got['permissions'])}")
    sys.exit(0)
sys.exit("Login request expired before it was approved.")
PY
fi

if [ $# -lt 3 ]; then
  echo "usage: $0 <prod|local> <METHOD> <PATH> [BODY_FILE|-]" >&2
  echo "       $0 login <prod|local> [client name]" >&2
  exit 2
fi

target=$1 method=$2 path=$3 body=${4:-}
resolve_target "$target"

if [ -z "${!var:-}" ] && [ -f "$keys_file" ]; then
  # shellcheck disable=SC1090
  set -a; . "$keys_file"; set +a
fi
if [ -z "${!var:-}" ]; then
  echo "$var is not set - run: $0 login $target" >&2
  exit 2
fi

args=(-sS -X "$method" -w '\nHTTP %{http_code}\n')
if [ -n "$body" ]; then
  args+=(-H 'Content-Type: application/json' --data-binary "@$body")
fi
# The process substitution must sit on curl's own command line: inside the
# array assignment above, its fd is closed before curl ever reads it.
curl "${args[@]}" -K <(printf 'header = "Authorization: Bearer %s"\n' "${!var}") "$base_url$path"
