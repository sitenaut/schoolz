---
name: deploy-schoolz
description: Ship committed schoolz changes to production via GitHub - push the branch, open/update a PR, merge it, and make sure the DB-migrate and Fly deploy GitHub Actions actually run to completion. Use when the user asks to deploy, ship, "push to prod", "merge and deploy", or "make sure it went live".
---

# Deploying schoolz to production

schoolz has **no dev/stage tier** - `main` is prod. Deploys are driven by two
chained GitHub Actions workflows, not a single "on push" pipeline, and that
chaining has a sharp edge this skill exists to catch.

## The workflow-chaining gotcha (read this first)

- **`.github/workflows/migrate.yml`** ("DB migrate") triggers on push to
  `main`, but **only if the push touches `backend/alembic/**` or
  `backend/models.py`** (or via manual `workflow_dispatch`).
- **`.github/workflows/deploy.yml`** ("Deploy") does **not** trigger on push
  at all - it only triggers via `workflow_run` when "DB migrate" *completes*
  (success or failure), or via manual `workflow_dispatch`.

So: a merge to `main` with no migration-relevant file changes runs **neither**
workflow automatically - migrate's path filter doesn't match, and deploy has
nothing to chain off of. Always check what actually fired; never assume a
merge alone shipped anything.

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
   (Don't delete the branch unless the user's workflow expects that - this
   repo's convention keeps `ecastillo-dev` alive across merges.)

5. **Check what actually triggered:**
   ```
   gh run list --branch main --limit 5
   ```
   - If "DB migrate" shows `push` as the trigger and is running/queued, wait
     for it (see step 6), then re-check that "Deploy" appears as a
     `workflow_run`-triggered run after it completes.
   - If nothing new appears at all (no migration-relevant files changed),
     deploy needs a **manual dispatch**:
     ```
     gh workflow run deploy.yml -f target=both
     ```
     (`target` can be `backend`, `frontend`, or `both`.)

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
   Common prior failure mode here: a "Deploy" run can fail even after
   "DB migrate" succeeds (seen 2026-09-09) - check the actual flyctl output,
   don't assume the migrate step is at fault just because it ran first.

8. **Report back** with: which workflows ran and their conclusions, and the
   live URLs (`https://schoolz.sitenaut.com`, `https://schoolz-api.sitenaut.com`)
   so the user can verify themselves.

## Don't

- Don't force-push or delete branches without being asked.
- Don't skip the "what actually triggered" check (step 5) - assuming a merge
  alone deployed something is exactly the mistake this skill exists to
  prevent.
- Don't run long verification scripts against prod from `fly ssh console` on
  an `app` machine - SSH doesn't count as traffic for fly-proxy's idle timer
  and the machine can auto-stop mid-script. Use the `scheduler` machine
  (always on) for one-off prod scripts if a deploy needs follow-up data work.
