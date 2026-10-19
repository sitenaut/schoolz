---
name: deploy-schoolz
description: Ship committed schoolz changes to production via GitHub - push the branch, open/update a PR, merge it, and make sure the Deploy GitHub Action actually runs to completion. Use when the user asks to deploy, ship, "push to prod", "merge and deploy", or "make sure it went live". Also holds the prod facts (which Supabase project is the prod DB, pooler host, Fly networking, running one-off prod scripts) - load it when diagnosing or changing anything in prod.
---

# Deploying schoolz to production

schoolz has **no dev/stage tier** - `main` is prod, and `main` only takes
pull requests whose `backend` and `frontend` checks pass (ruleset `main`).

## How a merge deploys (read this first)

**`.github/workflows/deploy.yml`** ("Deploy") runs on every push to `main`:

1. **CI** (`ci.yml`) runs again on the merged code. If it fails, nothing deploys.
2. **changes** compares `main` with the commit each Fly app is running (its
   image label `sha-<commit>`): `backend/**` changed -> `schoolz-api`,
   `frontend/**` changed -> `schoolz-web`, neither -> nothing deploys, which
   is correct. An image without a `sha-` label counts as changed.
3. **backend**, then **frontend**: each remembers the running image, deploys,
   smoke-checks it (API: `/health`, `/schools`, MCP `initialize` with the real
   Host; web: `/` and `/focus/`), and **redeploys the previous image** if the
   deploy or smoke check fails. The backend's `flyctl deploy` migrates first:
   `release_command` in `backend/fly.toml` runs `scripts/release.py` in a
   temporary machine with the app's secrets, before any machine is replaced.
   It only upgrades, waits at most 5 s for a lock, and a failure stops the
   deploy with the old version still up. It does nothing when the database is
   ahead of the image, and the rollback deploys without it.

A run that was cancelled or failed is caught up by the next push, since the
comparison is against what is running, not the previous push. By hand:
`gh workflow run deploy.yml -f target=<both|backend|frontend|scraper>` (main
only; `scraper` is hand-only). `migrate.yml` is by hand only and offers
`upgrade head`, `current` and `history`.

**The rollback is proven by a drill**: `gh workflow run deploy.yml -f
target=backend -f drill=true` (then again with `target=frontend`) deploys,
fails the smoke check on purpose, rolls back, and checks every machine runs
the previous image digest. Drill one app per run - with `both`, a failed
backend skips the frontend. Expect ~30 s of downtime: the rollback restarts
every machine at once (`--strategy immediate`), which is why `/health` after
it retries for two minutes. A rolled-back image has no `sha-` label, so the
next push redeploys that app; that is harmless.

## Steps

1. **Confirm the work is committed.** `git status --short` - if anything is
   uncommitted, stop and ask (or follow the user's explicit instruction) before
   committing. Never commit unless the user asked for this deploy.

2. **Push the current branch:**
   ```
   git push origin <branch>
   ```

3. **Find or open the PR:**
   ```
   gh pr list --state open --head <branch>
   ```
   If one already exists targeting `main`, pushing updates it in place - reuse
   it rather than opening a second one. Otherwise:
   ```
   gh pr create --title "..." --body "..." --base main --head <branch>
   ```
   Check `gh pr view <n> --json commits --jq '.commits | length'` first - an
   old branch may carry a large backlog of unmerged commits beyond the
   change just made. If it's more than just today's work, say so explicitly
   before merging - merging deploys everything in the PR, not just the
   latest commit.

4. **Merge it:**
   ```
   gh pr merge <n> --merge --delete-branch=false
   ```
   (Don't delete the branch at merge time. Once the deploy is verified in prod,
   delete the PR's own branch, remote and local, with `git branch -d` - see the
   `ship` skill, step 7. Never the long-lived dev branch or `main`.)

5. **Find the Deploy run the merge started:**
   ```
   gh run list --workflow deploy.yml --branch main --limit 3
   ```
   Its `changes` job log says what it decided to deploy and why. If a job
   was skipped, that is usually "nothing in that directory changed".

6. **Watch each run to completion.** Don't use `gh run watch` under the
   Monitor tool - its live-refreshing display repaints the same frame
   repeatedly and floods notifications. Instead poll quietly and let a single
   completion event fire:
   ```
   until [ "$(gh run view <run-id> --json status --jq .status)" = "completed" ]; do sleep 10; done
   gh run view <run-id> --json conclusion,jobs --jq '{conclusion, jobs: [.jobs[] | {name, conclusion}]}'
   ```
   Run this via Bash with `run_in_background: true` so it doesn't block, and
   check the follow-up notification rather than polling manually in the
   foreground.

7. **On failure**, pull the failing job's log before guessing:
   ```
   gh run view <run-id> --log-failed
   ```
   Check the actual flyctl output. A failed release step (migration) prints
   `release:` lines and the Alembic error in the Deploy step's log; nothing was
   replaced. A failed smoke check has already put the
   previous image back (look for the "Roll back" step's warning), so prod is
   on the old version: fix forward with a new PR. A migration is **not**
   rolled back - the old image runs against the new schema, which is why
   migrations must only add.

8. **Report back** with: which workflows ran and their conclusions, and the
   live URLs (`https://schoolz.sitenaut.com`, `https://schoolz-api.sitenaut.com`)
   so the user can verify themselves.

## Don't

- Don't force-push, and don't delete a branch before its deploy is verified in prod (`ship` step 7 covers the cleanup after).
- Don't skip the "what actually triggered" check (step 5) - assuming a merge
  alone deployed something is exactly the mistake this skill exists to
  prevent.
- Don't run long verification scripts against prod from `fly ssh console` on
  an `app` machine - SSH doesn't count as traffic for fly-proxy's idle timer
  and the machine can auto-stop mid-script. Use the `scheduler` machine
  (always on) for one-off prod scripts if a deploy needs follow-up data work.

## Prod facts

Live at `https://schoolz.sitenaut.com` and `https://schoolz-api.sitenaut.com`.

- **The prod DB is the Supabase project misleadingly named `billz-prod`** (billz's real data is in the equally misnamed `clockin`). `DATABASE_URL` must be the **Session Pooler** on `aws-1-us-east-1` — the direct host is IPv6-only on the free tier (unreachable from GitHub runners); `aws-0` answers "tenant not found". RLS on with no policies is correct: nothing uses the Data API.
- **Custom domains must be Cloudflare DNS-only (grey cloud)**, or Fly certs never verify.
- **The scraper is on Fly's private network** (`http://schoolz-scraper.internal:8765`): 6PN is IPv6-only, so bind `::`; and it must **never auto-stop** — private traffic bypasses fly-proxy, so nothing wakes it and `.internal` resolves only started machines. It runs the shared playwright-scraper image (`scraper/SOURCE_REF`), not code in this repo, and isn't in `deploy.yml`: ship with `scripts/deploy-scraper.sh` (`--rollback` puts the previous image back). The process command binds a dual-stack socket by hand because uvicorn's `--host ::` is IPv6-only and Fly's checks come over IPv4; 1 GB machines run one render each (`MAX_CONCURRENCY=1`).
- **`schoolz-api` needs `--proxy-headers --forwarded-allow-ips='*'`** — Fly forwards plain HTTP, so `Location` headers came out `http://` and clients dropped POST bodies on the downgrade. `*` is safe; only fly-proxy reaches the port.
- **One-off prod scripts** run on the `scheduler` machine (always on), file under `/app`; the filesystem resets on deploy. Never run long scripts on an `app` machine over SSH — SSH doesn't count as traffic and it auto-stops mid-run. `fly ssh console` is intermittently unavailable; retry, don't diagnose.
- **Private preschools' documents/school-info/staff-roster scans are disabled** — chain websites, never one success, just burst load.
- **Prerender** (`/prerender`, for crawlers) is single-flighted per path, and serves stale cache if a re-render fails.
- **Supabase auth**: email signup requires the confirmation click first (reads as "login broken"). Google SSO needs the client ID/secret in Supabase *and* the Supabase callback in the client's redirect URIs.