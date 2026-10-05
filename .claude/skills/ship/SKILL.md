---
name: ship
description: One-shot "commit, PR, merge, deploy" for schoolz through git and gh. Use when the user says "ship it", "commit, pr, merge, deploy", or invokes /ship. Runs the tests and build first, then commits, opens or reuses the PR, merges, and confirms the deploy went live.
user-invocable: true
---

# Ship schoolz: commit -> PR -> merge -> deploy

Invoking this skill (or saying "ship it") is the user's explicit go-ahead for
the whole chain, including the commit, the merge to `main` (which is prod) and
the deploy. Deploy mechanics and the workflow-chaining gotcha live in
`.claude/skills/deploy-schoolz/SKILL.md`; read it if anything below is unclear.

## 1. Check before committing

- `git status --short` and `git diff --stat`. Stage files **by name**, never
  `git add -A`. Leave out anything unrelated, scratch files, or anything that
  could hold a secret (`env/`, `.env*`).
- Run what the change touches, in Docker for the backend:
  - backend: `docker exec schoolz-api-local sh -c 'cd /app && python -m pytest -q'`
    (known unrelated failure: `test_kids_api.py::test_assignment_suggestion_is_cached_and_shared_across_the_class`)
  - frontend: `cd frontend && npm run test && npm run build`
- Stop and report if anything new fails. Don't ship red.

## 2. Commit

Message in a HEREDOC, why over what, ending with the attribution lines from the
session's system-reminder (`Co-Authored-By` and `Claude-Session`). New commits
only, never amend, never `--no-verify`.

## 3. PR

`git push -u origin <branch>`, then `gh pr list --state open --head <branch>`.
Reuse an open PR, else `gh pr create --base main` with a Summary and Test plan
body ending with the attribution line. Check
`gh pr view <n> --json commits --jq '.commits | length'`; if the branch carries
more than today's work, say so before merging.

## 4. Merge

`gh pr merge <n> --merge` (this repo keeps its long-lived dev branch alive; don't delete it).

## 5. Deploy, and confirm what actually ran

`gh run list --branch main --limit 5` after the merge.

- Change touched `backend/alembic/**` or `backend/models.py` (even a comment):
  "DB migrate" runs on push and chains into "Deploy" by itself. Wait for both.
- Otherwise nothing fires: `gh workflow run deploy.yml -f target=<backend|frontend|both>`.
  Pick the target from what changed; `both` when unsure. The scraper is **not**
  in `deploy.yml` (`fly deploy` from `scraper/`).

Wait quietly, one background command per run (never `gh run watch` under
Monitor, and no chained `sleep`):

```
until [ "$(gh run view <id> --json status -q .status)" = completed ]; do sleep 5; done
gh run view <id> --json conclusion -q .conclusion
```

Run it with `run_in_background: true`.

## 6. Verify and report

`curl -s -o /dev/null -w "%{http_code}\n"` the affected page on
`https://schoolz.sitenaut.com` (and `/health` on `https://schoolz-api.sitenaut.com`
for backend changes). Report in a line or two: PR number, which workflows ran and
their conclusion, and any manual follow-up (Supabase redirect URLs, prod data
backfills, scraper deploy).

On a failed run: `gh run view <id> --log-failed` before guessing.
