#!/usr/bin/env bash
# Backup of the LOCAL dev database (the compose Postgres volume). Prod is
# scripts/backup.sh. See docs/BACKUPS.md.
#
#   bash scripts/backup-local.sh              # dump now
#   bash scripts/backup-local.sh --if-stale   # do nothing if the newest dump is recent
#
# scripts/compose-local.sh runs this before up/down/rm, so there is normally
# nothing to schedule.
#
# Optional env:
#   SCHOOLZ_LOCAL_BACKUP_DIR        where the plain dumps go (default $HOME/backups/schoolz-local)
#   SCHOOLZ_LOCAL_BACKUP_OFFSITE    a folder that syncs off this machine; it gets an
#                                   age-encrypted copy. Defaults to the path written in
#                                   $XDG_CONFIG_HOME/schoolz/backup-offsite-dir, if that file exists.
#   SCHOOLZ_LOCAL_BACKUP_KEEP       dumps kept in each place (default 30)
#   SCHOOLZ_LOCAL_BACKUP_STALE_MIN  what --if-stale counts as recent, in minutes (default 60)
#   SCHOOLZ_POSTGRES_CONTAINER      default schoolz-postgres-local
#
# Exit 3 means the Postgres container is not running, so there was nothing to dump.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
container="${SCHOOLZ_POSTGRES_CONTAINER:-schoolz-postgres-local}"
dest="${SCHOOLZ_LOCAL_BACKUP_DIR:-$HOME/backups/schoolz-local}"
keep="${SCHOOLZ_LOCAL_BACKUP_KEEP:-30}"
stale_min="${SCHOOLZ_LOCAL_BACKUP_STALE_MIN:-60}"
recipient_file="$REPO_ROOT/backup/age-recipient.txt"

offsite="${SCHOOLZ_LOCAL_BACKUP_OFFSITE:-}"
offsite_file="${XDG_CONFIG_HOME:-$HOME/.config}/schoolz/backup-offsite-dir"
if [[ -z "$offsite" && -r "$offsite_file" ]]; then
  offsite="$(head -n 1 "$offsite_file")"
fi

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "[backup-local] $container is not running - nothing dumped" >&2
  exit 3
fi

mkdir -p "$dest"
chmod 700 "$dest"

if [[ "${1:-}" == "--if-stale" ]] && [[ -n "$(find "$dest" -maxdepth 1 -name 'schoolz-local_*.dump' -mmin "-$stale_min" -print -quit)" ]]; then
  exit 0
fi

# Newest $keep files matching a pattern survive; the names sort by time.
prune() {
  find "$1" -maxdepth 1 -name "$2" | sort -r | tail -n "+$((keep + 1))" | while read -r old; do rm -f "$old"; done
}

stamp="$(date +%Y-%m-%d_%H%M%S)"
dump="$dest/schoolz-local_$stamp.dump"
tmp="$dump.partial"
trap 'rm -f "$tmp"' EXIT

# pg_dump from inside the container: always the server's own version, and the
# credentials never leave it.
( umask 077; docker exec "$container" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$tmp" )

tables="$(docker exec -i "$container" pg_restore --list < "$tmp" | grep -c ' TABLE DATA ' || true)"
(( tables > 0 )) || { echo "[backup-local] dump lists no table data - keeping the older dumps" >&2; exit 1; }
mv "$tmp" "$dump"
echo "[backup-local] $dump ($(stat -c %s "$dump") bytes, $tables tables)"
prune "$dest" 'schoolz-local_*.dump'

[[ -n "$offsite" ]] || exit 0

# Same rule as prod: the dump holds children's records and third-party tokens,
# so it never leaves this machine unencrypted. It is encrypted to the prod
# backup key, so reading it back needs BACKUP_AGE_IDENTITY (docs/BACKUPS.md).
recipient="$(grep -m 1 '^age1' "$recipient_file" 2>/dev/null || true)"
[[ -n "$recipient" ]] || { echo "[backup-local] no age public key in backup/age-recipient.txt - no off-machine copy" >&2; exit 1; }
[[ -d "$offsite" ]] || { echo "[backup-local] off-machine folder is missing - no off-machine copy" >&2; exit 1; }

enc="$offsite/schoolz-local_$stamp.dump.age"
if command -v age >/dev/null; then
  age --recipient "$recipient" --output "$enc.partial" "$dump"
else
  docker run --rm -i alpine:3 sh -c 'apk add --no-cache --quiet age >/dev/null && age --recipient "$1"' _ "$recipient" < "$dump" > "$enc.partial"
fi
[[ -s "$enc.partial" ]] || { rm -f "$enc.partial"; echo "[backup-local] encryption produced nothing - no off-machine copy" >&2; exit 1; }
mv "$enc.partial" "$enc"
echo "[backup-local] encrypted copy written to the off-machine folder"
prune "$offsite" 'schoolz-local_*.dump.age'
