#!/usr/bin/env bash
# Run a command with the prod 1Password service account, but only after a super
# admin approves it in the schoolz admin (usually on their phone).
#
#   scripts/prod-secrets.sh run --reason "why" --secrets NAME,NAME -- <command...>
#   scripts/prod-secrets.sh init        # one-time, at an interactive terminal
#
# init sets the one unlock key, so running it on a second machine breaks the
# first: copy the encrypted token file between machines instead.
#
# How it works: the prod service-account token sits on this machine only
# encrypted; the key that decrypts it is a Fly secret on schoolz-api
# (SECRETS_UNLOCK_KEY). `run` asks the API for access, printing a link and a
# short code; the approver sees the reason, the exact command and the secret
# names; on approval the API hands over the key once, the token is decrypted in
# memory and the command is exec'd with OP_SERVICE_ACCOUNT_TOKEN set. The token
# and key are never printed, never in argv, and the API key is stripped from the
# command's environment. Docs: docs/ENV_SETUP.md.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
keys_file=${SCHOOLZ_API_KEYS_FILE:-"$root/env/api-keys.env"}
token_file=${SCHOOLZ_OP_PROD_TOKEN_FILE:-"${XDG_CONFIG_HOME:-$HOME/.config}/schoolz/op-prod-token.enc"}
base_url=${SCHOOLZ_API_URL_PROD:-https://schoolz-api.sitenaut.com}
web_url=${SCHOOLZ_WEB_URL_PROD:-https://schoolz.sitenaut.com}
fly_app=${SCHOOLZ_FLY_APP:-schoolz-api}
key_var=SCHOOLZ_API_KEY_PROD

die() { echo "$*" >&2; exit 2; }

# The token file is PBKDF2-encrypted. macOS's /usr/bin/openssl is LibreSSL,
# which has no -pbkdf2, so prefer a real OpenSSL (Homebrew's) when the one on
# PATH lacks it. Same format everywhere, so a file made on WSL opens here.
has_pbkdf2() { case "$("$1" enc -help 2>&1)" in *pbkdf2*) return 0 ;; esac; return 1; }
openssl_bin=${SCHOOLZ_OPENSSL:-openssl}
if ! has_pbkdf2 "$openssl_bin"; then
  for c in /opt/homebrew/opt/openssl@3/bin/openssl /usr/local/opt/openssl@3/bin/openssl \
           /opt/homebrew/opt/openssl/bin/openssl /usr/local/opt/openssl/bin/openssl; do
    if [ -x "$c" ] && has_pbkdf2 "$c"; then openssl_bin=$c; break; fi
  done
fi
usage() {
  echo "usage: $0 run --reason \"why\" --secrets NAME,NAME -- <command...>" >&2
  echo "       $0 init" >&2
  exit 2
}

cmd=${1:-}
[ -n "$cmd" ] || usage
shift

case "$cmd" in
init)
  has_pbkdf2 "$openssl_bin" || die "no openssl with -pbkdf2 (macOS: brew install openssl@3)"
  command -v fly >/dev/null || die "fly not found (needed to set SECRETS_UNLOCK_KEY on $fly_app)"
  [ -t 0 ] || die "run init at an interactive terminal: it asks for the token"
  printf 'Paste the prod service-account token (hidden): ' >&2
  read -rs token
  echo >&2
  [ -n "$token" ] || die "no token entered"
  unlock=$("$openssl_bin" rand -hex 32)
  mkdir -p "$(dirname "$token_file")"
  chmod 700 "$(dirname "$token_file")"
  umask 077
  printf %s "$token" | "$openssl_bin" enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass fd:3 -out "$token_file.new" 3<<<"$unlock"
  back=$("$openssl_bin" enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass fd:3 -in "$token_file.new" 3<<<"$unlock")
  [ "$back" = "$token" ] || { rm -f "$token_file.new"; die "encrypt/decrypt check failed; nothing changed"; }
  unset token back
  # Setting the secret restarts $fly_app's machines. On failure nothing is
  # replaced, so the previous token file and server key stay a working pair.
  if ! printf 'SECRETS_UNLOCK_KEY=%s\n' "$unlock" | fly secrets import -a "$fly_app"; then
    rm -f "$token_file.new"
    die "could not set SECRETS_UNLOCK_KEY on $fly_app; nothing changed"
  fi
  unset unlock
  mv "$token_file.new" "$token_file"
  chmod 600 "$token_file"
  echo "Done. Encrypted token saved to $token_file; unlock key set on $fly_app."
  echo "Re-run init to rotate either (a new service-account token or a new unlock key)."
  ;;

run)
  reason="" secrets=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --reason) reason=${2:-}; shift 2 || usage ;;
      --secrets) secrets=${2:-}; shift 2 || usage ;;
      --) shift; break ;;
      *) usage ;;
    esac
  done
  [ -n "$reason" ] && [ -n "$secrets" ] && [ $# -gt 0 ] || usage
  [ -r "$token_file" ] || die "no encrypted token at $token_file: run  $0 init  first"
  if [ -z "${!key_var:-}" ] && [ -f "$keys_file" ]; then
    # shellcheck disable=SC1090
    set -a; . "$keys_file"; set +a
  fi
  [ -n "${!key_var:-}" ] || die "$key_var is not set - run: scripts/schoolz-api.sh login prod"
  export "$key_var"

  # The program goes in as -c text, not on stdin: the approved command inherits
  # this script's stdin, and a heredoc there would hand it an empty pipe (op
  # then reads "piped JSON" and fails; interactive commands lose the terminal).
  read -r -d '' prog <<'PY' || true
import json, os, shlex, subprocess, sys, time, urllib.error, urllib.request

base_url, web_url, key_var, token_file, reason, secrets_csv, openssl_bin = sys.argv[1:8]
cmd = sys.argv[9:]  # argv[8] is the "--" separator
names = sorted({n.strip() for n in secrets_csv.split(",") if n.strip()})
command_text = shlex.join(cmd)
if len(command_text) > 1000:
    sys.exit("The command is too long to put in a request (1000 characters).")
api_key = os.environ[key_var]


def call(path, body):
    req = urllib.request.Request(
        base_url + path,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        if exc.code in (401, 403):
            sys.exit(f"The API rejected this key ({exc.code}). Get a new one: scripts/schoolz-api.sh login prod")
        sys.exit(f"POST {path} failed: {exc.code} {detail}")


start = call(
    "/admin/secret-requests",
    {"client_name": f"Claude Code on {os.uname().nodename}"[:100], "reason": reason, "command": command_text, "secret_names": names},
)
code = start["user_code"]
print(f"Approve prod secret access: {web_url}/admin/secret-requests/approve?code={code}", flush=True)
print(f"Check the page shows the code {code}. Reading: {', '.join(names)}", flush=True)
print(f"Will run: {command_text}", flush=True)
print(f"Waiting up to {start['expires_in'] // 60} minutes...", flush=True)

deadline = time.time() + start["expires_in"]
got = None
while time.time() < deadline:
    time.sleep(start["interval"])
    polled = call("/admin/secret-requests/poll", {"device_code": start["device_code"]})
    if polled["status"] == "pending":
        continue
    if polled["status"] != "approved":
        sys.exit(f"Request {polled['status']}.")
    got = polled
    break
if got is None:
    sys.exit("Request expired before it was approved.")

# The approver read this command; refuse to run anything else.
if got["command"] != command_text or sorted(got["secret_names"]) != names:
    sys.exit("The approved request doesn't match what was asked. Not running anything.")

dec = subprocess.run(
    [openssl_bin, "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-pass", "stdin", "-in", token_file],
    input=(got["unlock_key"] + "\n").encode(),
    capture_output=True,
)
if dec.returncode != 0 or not dec.stdout.strip():
    sys.exit(
        "Could not decrypt the prod token with the unlock key: init was likely run on another machine. "
        f"Copy that machine's {token_file} here (docs/ENV_SETUP.md); don't re-run init."
    )

env = {k: v for k, v in os.environ.items() if k != key_var}
env["OP_SERVICE_ACCOUNT_TOKEN"] = dec.stdout.decode().strip()
print("Approved. Running.", flush=True)
try:
    os.execvpe(cmd[0], cmd, env)
except FileNotFoundError:
    sys.exit(f"{cmd[0]}: command not found")
PY
  exec python3 -c "$prog" "$base_url" "$web_url" "$key_var" "$token_file" "$reason" "$secrets" "$openssl_bin" -- "$@"
  ;;

*) usage ;;
esac
