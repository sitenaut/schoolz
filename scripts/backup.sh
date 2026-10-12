#!/usr/bin/env bash
# Backup: an encrypted Postgres dump written to the backups bucket.
# See docs/BACKUPS.md.
#
#   bash scripts/backup.sh            # needs pg_dump, age and rclone on PATH
#   bash scripts/backup.sh --docker   # runs itself in a container that has them
#
# Required env:
#   BACKUP_DATABASE_URL      postgresql://… (session pooler; a read-only role is enough)
#   BACKUP_S3_ENDPOINT       https://<account>.r2.cloudflarestorage.com
#   BACKUP_S3_ACCESS_KEY / BACKUP_S3_SECRET_KEY
# Optional env:
#   BACKUP_BUCKET            default schoolz-backup
#   BACKUP_AGE_RECIPIENT_FILE default backup/age-recipient.txt
#   BACKUP_MIN_BYTES         dump smaller than this fails the run (default 50000)
#   BACKUP_PG_IMAGE          image for --docker (default postgres:17-alpine; client must be >= server)
#   BACKUP_DOCKER_NETWORK    docker network for --docker (to reach a compose Postgres)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--docker" ]]; then
  net=()
  [[ -n "${BACKUP_DOCKER_NETWORK:-}" ]] && net=(--network "$BACKUP_DOCKER_NETWORK")
  exec docker run --rm "${net[@]}" \
    -e BACKUP_DATABASE_URL -e BACKUP_S3_ENDPOINT -e BACKUP_S3_ACCESS_KEY -e BACKUP_S3_SECRET_KEY \
    -e BACKUP_BUCKET -e BACKUP_MIN_BYTES -e BACKUP_AGE_RECIPIENT_FILE \
    -v "$REPO_ROOT:/repo:ro" -w /repo \
    "${BACKUP_PG_IMAGE:-postgres:17-alpine}" \
    sh -c 'apk add --no-cache --quiet bash age rclone >/dev/null && exec bash scripts/backup.sh'
fi

: "${BACKUP_DATABASE_URL:?BACKUP_DATABASE_URL is required}"
: "${BACKUP_S3_ENDPOINT:?BACKUP_S3_ENDPOINT is required}"
: "${BACKUP_S3_ACCESS_KEY:?BACKUP_S3_ACCESS_KEY is required}"
: "${BACKUP_S3_SECRET_KEY:?BACKUP_S3_SECRET_KEY is required}"
bucket="${BACKUP_BUCKET:-schoolz-backup}"
recipient_file="${BACKUP_AGE_RECIPIENT_FILE:-$REPO_ROOT/backup/age-recipient.txt}"
min_bytes="${BACKUP_MIN_BYTES:-50000}"

for tool in pg_dump pg_restore age rclone; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool (try --docker)" >&2; exit 2; }
done
grep -q '^age1' "$recipient_file" 2>/dev/null || { echo "no age public key in $recipient_file" >&2; exit 2; }

# rclone remote "r2", configured from env so nothing is written to disk.
export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Other
export RCLONE_CONFIG_R2_ENDPOINT="$BACKUP_S3_ENDPOINT"
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
export RCLONE_CONFIG_R2_REGION=auto RCLONE_S3_NO_CHECK_BUCKET=true RCLONE_LOG_LEVEL=ERROR

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dump="$work/schoolz-$stamp.dump"

# SQLAlchemy-style URLs name a driver that libpq does not understand.
pg_url="${BACKUP_DATABASE_URL/+asyncpg/}"
pg_url="${pg_url/+psycopg/}"

echo "[backup] dumping schema public"
pg_dump --format=custom --no-owner --no-privileges --schema=public --file="$dump" "$pg_url"

size="$(stat -c %s "$dump")"
tables="$(pg_restore --list "$dump" | grep -c ' TABLE DATA ' || true)"
echo "[backup] dump is $size bytes, $tables tables with data"
(( size >= min_bytes )) || { echo "[backup] dump smaller than $min_bytes bytes — refusing to upload" >&2; exit 1; }
(( tables > 0 )) || { echo "[backup] dump lists no table data — refusing to upload" >&2; exit 1; }

# The dump holds children's records and third-party tokens, so it never leaves
# this machine unencrypted.
age --recipients-file "$recipient_file" --output "$dump.age" "$dump"
rm -f "$dump"

daily="postgres/daily/schoolz-$stamp.dump.age"
rclone copyto "$dump.age" "r2:$bucket/$daily"
remote_size="$(rclone size --json "r2:$bucket/$daily" | sed -E 's/.*"bytes":([0-9]+).*/\1/')"
[[ "$remote_size" == "$(stat -c %s "$dump.age")" ]] || { echo "[backup] uploaded size mismatch" >&2; exit 1; }
echo "[backup] uploaded $daily ($remote_size bytes)"

if [[ "$(date -u +%d)" == "01" ]]; then
  rclone copyto "$dump.age" "r2:$bucket/postgres/monthly/schoolz-$stamp.dump.age"
  echo "[backup] kept a monthly copy"
fi

# Retention: 35 days of dailies, 13 months of monthlies.
rclone delete --min-age 35d "r2:$bucket/postgres/daily/"
rclone delete --min-age 400d "r2:$bucket/postgres/monthly/"

echo "[backup] done $stamp"
