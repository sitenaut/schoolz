# Bucket 3: capturing Google Classroom / Genesis via a logged-in browser

`docs/DISTRICT_COMMUNICATION_REPORT.md` splits what a family needs into three
buckets and says schoolz deliberately stops before the third one: *"a child's
individual educational world — communication with their specific teachers,
their assignments, how they're tracked and managed day to day"* (Google
Classroom, Genesis, ClassDojo, Remind, Teaching Strategies, ...). This note
records the approach that was actually found to work for reaching that data,
since none of it lives anywhere schoolz's own scanner model (public,
unauthenticated, server-side, admin-managed) can touch.

## Why the obvious approaches don't work here

- **OAuth against the Classroom/Genesis APIs** — tried, didn't work. A child's
  Google account is a district-managed Google Workspace for Education
  identity, not a personal Google account; the district (as the Workspace
  admin) controls which third-party OAuth clients are allowed to request
  `classroom.*` scopes against student accounts at all, and a personal/
  unapproved app has no path to get that consent. Genesis has no public API
  in the first place.
- **Scripted/headless login** — tried, didn't work. Automating a sign-in
  (Playwright, a login script, etc.) hits Google's bot/automation detection
  and the account's own MFA/session policies almost immediately — this is
  the same category of problem schoolz's own scraper explicitly avoids by
  only ever touching public, unauthenticated pages (see `CLAUDE.md`'s
  "Access model" section). A district-managed student identity is a much
  higher-scrutiny target for this than a public school website.

Both failure modes share a root cause: anything that presents credentials or
simulates a login *as* the automation is exactly what these systems are
designed to detect and block.

## What worked: read the DOM of a session the human already opened

The workflow that actually produced usable data:

1. The parent logs into their daughter's Google Classroom **normally**, in
   their own Chrome, as themselves — no automation touches the login at all.
2. A desktop app (Claude Desktop) listens locally and captures the fully
   *rendered* page — not a raw HTTP fetch of the URL, the same DOM the human
   is looking at, including everything React/Classroom's client-side JS
   painted in after login. A real capture from this workflow is saved at
   `../englishClassroomstream.html` (+ its `_files/` sibling folder of
   images/scripts/fonts) — a complete-page save of a Classroom stream view,
   confirmed to contain real assignment titles, due dates ("due Tomorrow",
   "due Friday"), and per-item Classroom metadata (`aria-label="Assignment:
   ..."` etc.) for every post in the stream.
3. That captured page is handed to Claude for extraction — the same kind of
   structured-extraction pass schoolz's own `content_extractor.py` runs over
   Smore newsletter blocks, just pointed at a different source shape.
4. The extracted assignments/due-dates/materials feed a consolidated view of
   everything the child has to do, instead of the parent manually opening
   every class's stream and reading it themselves.

**Why this sidesteps the two failed approaches**: nothing here ever
authenticates *as* an automated agent. The human's own already-authorized
browser session does 100% of the authentication and rendering; the desktop
app's job is only to read back the resulting page content. There's no OAuth
consent to obtain, no login to script, and no bot-detection surface to trip,
because from Google's/Genesis's point of view this is indistinguishable from
a person reading their own account in their own browser — because it is one.

## What this is not

- **It isn't unattended.** Every capture needs the parent to actually be
  logged in and on the page in that moment (or the app to trigger the
  capture while that session is live) — there is no equivalent to schoolz's
  `scheduler` re-checking a public URL every 12 hours with nobody present.
  The tradeoff for working at all is that it can't run as a background job.
- **It isn't a schoolz feature.** It requires the parent's/child's own
  district credentials to already be in a live browser session on the same
  machine the capture happens on — the opposite of schoolz's "public,
  admin-managed, no personal login required" model (see the "Access model"
  section of `CLAUDE.md`). It's recorded here as prior art for bucket 3, in
  case that boundary is ever revisited, not as something to build into the
  schoolz backend.
- **It isn't scoped to one page.** The same technique generalizes to any
  bucket-3 source that has no usable API and blocks scripted login but is
  reachable by a real logged-in human — Genesis assignment/grade views being
  the other concrete target named when this was discussed, alongside
  Classroom.

## Open questions if this gets picked up as real work

- What triggers a capture — a manual "grab this page" action in the desktop
  app each time, or something that watches for navigation to a known
  Classroom/Genesis URL pattern and prompts automatically?
- How many classes'/children's streams need capturing per "refresh", and how
  stale is tolerable before the parent needs to recapture?
- Where does the extracted, consolidated "what's due" view live — is it
  local-only (never leaves the parent's machine, matching the sensitivity
  bucket 3 was called out for), or does it need a durable store the way
  schoolz's own `SchoolContentItem` does?
