# Migrations — rules

These apply to every revision under `versions/`.

## Additive only
- Add and backfill. No `op.drop_table`, `op.drop_column`, `TRUNCATE`,
  `DELETE FROM` or `DROP ...` in `upgrade()`. CI enforces this
  (`backend/scripts/check_migrations_additive.py`; revisions up to 0099 predate
  the rule).
- If one truly has to remove data: take a backup first (`docs/BACKUPS.md`),
  rehearse on a restored copy, and add a line
  `# destructive-ok: <why, which backup>` to the revision. Ask the owner before
  writing one.
- A migration that rewrites existing rows also needs a backup first, even
  though CI cannot tell.

## Expand, then contract
A backend deploy runs the migration first (Fly's `release_command`,
`backend/scripts/release.py`), then replaces machines one by one; old code
keeps serving during the roll, and a rollback puts old code back on the new
schema. So each migration must work with the previous release's code:
- New columns are nullable or have a server default.
- Rename = add the new column, copy, switch the code, and only later (if ever)
  stop using the old one. Never rename in place.
- Stop reading a column in one deploy; never drop it in the same one.

## Writing a revision
- File name `NNNN_<what>.py`, `revision` = `NNNN`, `down_revision` = the
  current head. One head only (CI checks).
- `--autogenerate` output is a draft, not a migration: read every line. It is
  where an unintended drop comes from.
- Data seeded by a migration (job params, sources) must only fill what is
  missing, never overwrite a value someone may have changed in the admin UI.
- Locks: migrations run with `lock_timeout = 5s` and `statement_timeout = 4min`
  (`env.py`). On a busy table prefer `CREATE INDEX CONCURRENTLY` inside
  `op.get_context().autocommit_block()`. A long backfill sets its own
  `SET LOCAL statement_timeout` and needs `release_command_timeout` raised in
  `backend/fly.toml`.
- `downgrade()` is never run against prod by automation: the migrate workflow
  offers only `upgrade head`, `current` and `history`.

## Checking a revision
```bash
./scripts/alembic_env.sh local upgrade head              # apply locally
python backend/scripts/check_migrations_additive.py     # what CI runs
```
CI also applies every migration to an empty Postgres and checks there is one
head.
