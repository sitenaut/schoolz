# Backups

## What is backed up

`scripts/backup.sh` writes to the `schoolz-backup` R2 bucket:

| Path in the bucket | Contents | Kept for |
|---|---|---|
| `postgres/daily/schoolz-<UTC stamp>.dump.age` | `pg_dump` of schema `public`, custom format, encrypted with age | 35 days |
| `postgres/monthly/…` | The dump taken on the 1st of each month | 400 days |

That is everything: schoolz keeps no object storage, and captured pages and
uploaded files are columns in Postgres. The Supabase-managed schemas (`auth`,
`storage`) are not in the dump. User logins live in Supabase Auth and are
restored by Supabase, not by this procedure.

## Encryption

The dump contains children's records and third-party tokens, so it is encrypted
before upload.

- Public key: `backup/age-recipient.txt` (committed). Anyone can encrypt to it.
- Private key: the `BACKUP_AGE_IDENTITY` item in the `schoolz-prod` vault, and
  nowhere else. **Without it no backup can be restored.**

## Schedule

`.github/workflows/backup.yml`, nightly at 07:17 UTC, and on demand from the
Actions tab (`gh workflow run backup.yml`). It reads `DATABASE_URL`,
`BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY` and `BACKUP_S3_SECRET_KEY` from the
GitHub `prod` environment; the R2 key can read and write `schoolz-backup` only.

The run fails, and uploads nothing, if the dump is under 50 kB or lists no table
data. Nothing alerts on a failed run beyond GitHub's own notification, so check
`gh run list --workflow backup.yml` now and then.

## Restore drill

Proves the newest backup can be decrypted and restored. It restores into a
throwaway Postgres container and touches nothing else.

```bash
bash scripts/prod-secrets.sh run --reason "restore drill" \
  --secrets BACKUP_AGE_IDENTITY,BACKUP_S3_ENDPOINT,BACKUP_S3_ACCESS_KEY,BACKUP_S3_SECRET_KEY,DATABASE_URL \
  -- op run --env-file env.op/backup.prod.env -- bash scripts/restore-drill.sh
```

It prints the Alembic version and row counts for the main tables. Compare them
with what you expect. Run it quarterly and before any risky migration, and
record the date:

| Date | Backup restored | Result |
|---|---|---|
| 2026-10-12 | First prod backup `schoolz-20261012T232858Z`, taken by hand | 63 tables; 8 users, 7 students, 228 schools, 56,724 content items; Alembic `0099` |

## Restoring for real

1. Run the drill with `DRILL_KEEP=1` and check the data in the container.
2. Stop writers: scale the Fly API (`app` and `scheduler`) to zero.
3. Download the chosen dump and decrypt it with the private key from the vault:
   `age --decrypt --identity <key file> --output schoolz.dump <file>.dump.age`
4. Restore into the target database. The dump's row-level-security policies
   name the `grafana_ro` role, which was created by hand in prod: the existing
   prod database has it, a new one needs it created first (the drill makes a
   stand-in). For a full replacement, drop schema `public` first; the dump
   recreates it:
   `pg_restore --no-owner --no-privileges --exit-on-error --dbname "$DATABASE_URL" schoolz.dump`
5. Check `alembic current` matches the code being deployed, then start the apps.
