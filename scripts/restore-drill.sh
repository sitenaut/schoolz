#!/usr/bin/env bash
# Restore drill: fetch the newest database backup, decrypt it, restore it into
# a throwaway Postgres container and print what came back. Touches nothing
# else. See docs/BACKUPS.md.
#
#   bash scripts/restore-drill.sh
#
# Required env:
#   BACKUP_S3_ENDPOINT, BACKUP_S3_ACCESS_KEY, BACKUP_S3_SECRET_KEY
#   BACKUP_AGE_IDENTITY    the age private key itself (AGE-SECRET-KEY-1…), from the vault
# Optional env:
#   BACKUP_BUCKET          default schoolz-backup
#   BACKUP_PG_IMAGE        default postgres:17-alpine (must be >= the server that was dumped)
#   DRILL_KEEP=1           leave the container running for inspection
set -euo pipefail

: "${BACKUP_S3_ENDPOINT:?BACKUP_S3_ENDPOINT is required}"
: "${BACKUP_S3_ACCESS_KEY:?BACKUP_S3_ACCESS_KEY is required}"
: "${BACKUP_S3_SECRET_KEY:?BACKUP_S3_SECRET_KEY is required}"
: "${BACKUP_AGE_IDENTITY:?BACKUP_AGE_IDENTITY is required}"
bucket="${BACKUP_BUCKET:-schoolz-backup}"
image="${BACKUP_PG_IMAGE:-postgres:17-alpine}"

name="schoolz-restore-drill-$$"
cleanup() { [[ "${DRILL_KEEP:-}" == "1" ]] || docker rm -fv "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$name" \
  -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=drill \
  -e BACKUP_S3_ENDPOINT -e BACKUP_S3_ACCESS_KEY -e BACKUP_S3_SECRET_KEY -e BUCKET="$bucket" \
  "$image" >/dev/null
# On stdin, so the key is in neither argv nor the container's environment.
printf '%s\n' "$BACKUP_AGE_IDENTITY" | docker exec -i "$name" sh -c 'umask 077; cat > /tmp/identity.txt'

docker exec "$name" sh -c '
set -eu
apk add --no-cache --quiet age rclone >/dev/null
export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Other RCLONE_CONFIG_R2_REGION=auto
export RCLONE_CONFIG_R2_ENDPOINT="$BACKUP_S3_ENDPOINT"
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
export RCLONE_S3_NO_CHECK_BUCKET=true RCLONE_LOG_LEVEL=ERROR

latest="$(rclone lsf "r2:$BUCKET/postgres/daily/" | sort | tail -1)"
[ -n "$latest" ] || { echo "[drill] no backups found in $BUCKET/postgres/daily/" >&2; exit 1; }
echo "[drill] newest backup: $latest"
rclone copyto "r2:$BUCKET/postgres/daily/$latest" /tmp/backup.age
age --decrypt --identity /tmp/identity.txt --output /tmp/backup.dump /tmp/backup.age
rm -f /tmp/identity.txt /tmp/backup.age

until pg_isready -q -U postgres -d drill; do sleep 1; done
# The dump recreates schema public itself.
psql -q -U postgres -d drill -c "drop schema public cascade"
# Row-level-security policies in the dump name roles that were created by hand
# in prod (grafana_ro); a plain Postgres needs stand-ins before they can be made.
pg_restore --section=post-data --file=- /tmp/backup.dump \
  | sed -nE "s/^CREATE POLICY .* TO ([a-z_0-9, ]+) (USING|WITH CHECK).*/\1/p" \
  | tr "," "\n" | tr -d " " | sort -u | grep -vx public \
  | while read -r role; do psql -q -U postgres -d drill -c "create role \"$role\" nologin"; done
pg_restore --no-owner --no-privileges --exit-on-error -U postgres -d drill /tmp/backup.dump
echo "[drill] restored. alembic version:"
psql -U postgres -d drill -Atc "select version_num from alembic_version"
echo "[drill] row counts:"
for t in users students guardian_student_links districts schools school_content_items smore_newsletters local_events scheduled_jobs; do
  n="$(psql -U postgres -d drill -Atc "select count(*) from \"$t\"" 2>/dev/null || echo "missing")"
  printf "  %-24s %s\n" "$t" "$n"
done
echo "[drill] tables restored: $(psql -U postgres -d drill -Atc "select count(*) from information_schema.tables where table_schema = '"'"'public'"'"'")"
'
echo "[drill] ok"
