# Backpack — desktop app design (bucket 3)

Design only. Nothing here is built. Companion to
`docs/BUCKET3_CLASSROOM_CAPTURE.md`, which records *why* the browser-capture
approach is the one that works; this document is *what to build on top of it*.

**Working name**: Backpack (Horace Mann's newsletter already calls itself the
"Digital Backpack" — the name is a placeholder, steal a better one).

**The one-line goal**: a parent opens their kid's Google Classroom and Genesis
the way they already do, and ends up with one list of everything that's due,
across every class and every child, without ever doing "Save As" again.

> **Hard constraint, confirmed**: the district blocks unapproved Chrome
> extensions in the daughter's Chrome profile. The block is profile-scoped —
> it's the parent's own unenrolled machine, with her managed Google account
> added as a Chrome profile — so Chrome's user-level cloud policy
> (`ExtensionInstallBlocklist` / `ExtensionSettings`) applies to *that profile
> only*. Loading an unpacked extension in developer mode is normally caught by
> the same policy, so that isn't an escape hatch either.
>
> This kills the extension-based capture layer in *her* profile — but the
> block attaches to the Chrome-browser sign-in, not to the website session,
> so a candidate workaround exists: a separate, unmanaged Chrome profile that
> is never signed into as a browser, with her Classroom/Genesis opened as a
> plain website login inside it. **Unverified as of this writing — see the
> Verification protocol immediately below, which must pass before this
> becomes the primary design rather than a hypothesis.** Everything
> downstream of the capture envelope — reduction, extraction, identity, UI —
> is unaffected either way.

---

## Verification protocol (run this before building anything)

The whole primary path (Tier 1, below) rests on one unconfirmed assumption:
that a Chrome profile can hold her Classroom session as a *website* login
without ever fetching the district's user cloud policy. This is a 15-minute
test, and nothing past this section should get built until it passes.

**The condition, stated precisely**: your own Chrome, a brand-new profile
dedicated to this, *her* Classroom logged in inside it — not her Chrome
profile with the district account signed into the browser.

1. Create a new Chrome profile. Name it something unambiguous — "Schoolwork,"
   not "Emma" — so it's never mistaken for a daily-driver profile.
2. **Before logging in**, go to `chrome://settings/syncSetup` in that profile
   and turn **off** "Allow Chrome sign-in." This is the step that keeps the
   next one from silently promoting a website login into a browser login.
3. Install a harmless test extension (anything from the Web Store).
4. Navigate to Classroom and log in with her account, in that tab, as a
   website. Do not use "Sign in to Chrome."
5. Check `chrome://policy` — it should list no policies. Check
   `chrome://management` — it should say the browser isn't managed. If either
   shows district policy, the account-consistency trap fired (see below);
   stop and reconsider before going further.
6. Confirm the extension still runs and its content script still fires on
   the Classroom page.

**Pass** → proceed with Tier 1 as designed below.
**Fail at step 5** → Chrome pulled district policy into the profile anyway.
Don't keep testing in the same profile — delete it and start over in a fresh
one, and treat the design as needing the CDP-only fallback noted under Tier 1.
**Fail differently — login succeeds but Classroom itself refuses to load
content** → this is Context-Aware Access (the district requiring a *managed*
browser to reach Workspace apps at all, independent of extensions or Chrome
sign-in). If this happens, no unmanaged-profile approach works, extension or
otherwise, and Tier 0 (drop-and-watch) is the only path available. Worth
finding out now rather than after building Tier 1.

---

## Design principles

These are the four that actually constrain the design. Everything below falls
out of them.

1. **The human authenticates; the app only reads.** The app never logs in,
   never submits a form, never touches an auth flow. That's the line that got
   OAuth and scripted login blocked, and it's the one that must not move.
   Once a session is live, the app may navigate between already-authenticated
   pages — that's following a bookmark, not automating a login.
2. **Never read credentials.** Not cookies, not tokens, not `localStorage`,
   not the password manager. The capture surface is the rendered DOM and
   nothing else — the extension's declared permissions should make this
   readable straight off the manifest. **If Tier 2 gets built**, the app
   additionally launches (but never reads) the Schoolwork profile's directory,
   which holds a live cookie jar it never opens or parses — a slightly
   weaker guarantee than Tier 1 alone, since it becomes a property of the
   code rather than of the filesystem layout. Worth knowing that's the trade,
   should that tier ever get built.
3. **Local-first, no server.** This is a child's education record. It lives on
   the parent's machine. There's no account, no sync, and no backend unless
   that's decided later as its own deliberate call.
4. **Freshness is always on screen.** Captures can't run unattended — that's
   the price of the approach working at all. A list that silently goes stale
   is worse than no list, because the parent will trust it. Every view shows
   how old its data is.

---

## Architecture

**Three capture tiers, one ingestion point.** The tiers exist because the
transport is the fragile part — it's the only piece the district can break —
so the design degrades deliberately instead of having a single point of
failure. Everything from the capture envelope onward is shared.

```
  ┌─ Tier 0 ─ always works, zero integration, build first ────┐
  │  Parent hits Ctrl+S ("Webpage, Complete") in ANY browser, │
  │  including her managed profile → watched folder           │
  └──────────────────────────────┬────────────────────────────┘
  ┌─ Tier 1 ─ primary, pending Verification protocol ─────────┤
  │  Dedicated UNMANAGED Chrome profile ("Schoolwork"),       │
  │  her account signed in as a website, never as the browser.│
  │  MV3 extension lives here: match → settle → reduce →      │
  │  native-messaging handoff. Parent clicks through by hand. │
  └──────────────────────────────┬────────────────────────────┘
  ┌─ Tier 2 ─ optional add-on, same profile as Tier 1 ────────┤
  │  App launches that SAME profile with a debug port and     │
  │  drives navigation over CDP — the extension still does    │
  │  the actual capture. Turns "click through 8 pages" into   │
  │  "click Run pass."                                        │
  └──────────────────────────────┬────────────────────────────┘
                                 ▼
                   reduce  →  capture envelope
                                 ▼
              ┌──────────────────────────────────┐
              │  Backpack desktop app (Electron) │
              │  store · extract · dedup · UI    │
              └──────────────┬───────────────────┘
                             ▼  HTTPS, reduced text only
                    Anthropic API (extraction)
```

### Tier 0 — Drop and watch (build this first)

The parent saves the page (Ctrl+S, "Webpage, Complete") into a watched folder;
the app ingests it, reduces it, and extracts. **This is already proven** — the
reference capture at `../englishClassroomstream.html` is exactly this
artifact, produced by hand, and it contains everything the extractor needs.

It works in her managed profile, needs no install, and no policy can block it.
It's two keystrokes per page — worse than automatic, but it means the app is
useful before a single line of browser integration exists, and it's the
permanent fallback if Google, the district, or Chrome's own policy behavior
ever closes off Tier 1.

### Tier 1 — Extension in a dedicated unmanaged profile (the primary path)

**Gated on the Verification protocol above passing.** The condition, stated
precisely because it's the whole design: **your own Chrome, a profile that is
never signed in as a browser, her Classroom/Genesis opened as a website login
inside it.** Once that holds, there is no meaningful difference from schoolz's
own extraction posture — this is just a normal MV3 extension in a normal
unmanaged profile, matching against a page the human is legitimately looking
at.

- **Declared permissions**: `nativeMessaging`, `scripting`, and host
  permissions for *only* the allowlisted origins. Explicitly not `cookies`,
  `webRequest`, or `<all_urls>` — principle 2 should be readable straight off
  the manifest.
- Auto-triggers on URL match; no button to remember. `all_frames: true` for
  Genesis (see Adapters).
- Visible, never silent — a small toast on capture: "Backpack captured this
  page · Undo." A tool quietly vacuuming a child's data in the background is
  the wrong posture even in a profile you built for exactly this.
- Talks to the desktop app over native messaging (local IPC, no open port —
  Chrome only launches a host whose manifest names the extension ID, which
  is authentication for free).

This profile is used for nothing else — no personal browsing, no other
accounts. Treating it as a single-purpose appliance, not a browsing profile,
is what keeps "never signed in as a browser" from drifting over time.

### Tier 2 — Self-driving navigation, same profile (optional add-on)

Once Tier 1 is proven, the *same* unmanaged profile can be launched by the app
as an ordinary subprocess with a debug port:

```
chrome --user-data-dir=<the Schoolwork profile dir> --remote-debugging-port=<port>
```

The app connects over CDP purely to call `Page.navigate` between the
checklist's URLs — the extension already installed in that profile does the
actual capture, so CDP here is a remote control, not a second capture path.
This turns the capture pass from "click through eight pages" into "click Run
pass," with no new trust boundary: it's the same profile, the same session,
the same extension.

Two things that matter if this gets built:

- **Launch Chrome yourself; never through Playwright's or Puppeteer's
  launcher.** Their launchers add `--enable-automation` and similar flags,
  which set `navigator.webdriver` — exactly what trips Google's "this browser
  or app may not be secure" block. Spawn the binary directly and *connect*
  (`puppeteer.connect({ browserURL })` or raw CDP).
- **Pace navigation like a human** — a second or two between pages, not eight
  `Page.navigate` calls in 400ms. Still principle 1: this authenticates
  nothing, it follows bookmarks in a session the human already opened.

Skip this tier entirely at first. Tier 1 alone — a parent clicking through
their own bookmark list with the extension silently capturing behind them —
is a complete, working product.

### The desktop app (Electron)

Electron over Tauri purely for stack reuse — React/TS, same as the schoolz
frontend, and Node makes both the native-messaging host and (if Tier 2 gets
built) the CDP client trivial to ship in one binary.

---

## Why this shape and not the alternatives

- **Extension inside her managed Chrome profile.** The original design. Dead
  on arrival — a webpage can't block an extension, but Chrome policy can, and
  that policy attaches to the profile that's signed into *the browser* with
  her managed account. Developer-mode loading is caught by the same policy,
  and `DeveloperToolsAvailability` may be restricted in that profile too.
- **A dedicated CDP-driven "capture window" as the primary path (an earlier
  draft of this doc).** Works, but it's strictly more machinery than Tier 1
  for the same result: it reimplements DOM reading over
  `Runtime.evaluate` when a normal content script already does that job, and
  it has no visible "captured" affordance the way an extension's toast does.
  Once the unmanaged-profile workaround is confirmed, an extension in that
  profile is simpler and is what Tier 1 now is. The CDP approach survives
  only as Tier 2 — driving navigation in that same profile, not reading DOM.
- **Embedded browser inside Electron (BrowserView with a persistent
  partition).** Tempting: one install, no extension, the app walks every class
  itself. It fails at the first step — Google actively blocks sign-in from
  embedded/webview contexts, and a district-managed Workspace account is
  exactly the population that block targets hardest. The parent would never
  get logged in. Rejected outright — note the contrast with Tier 2, which
  looks superficially similar but is categorically different: it's the real
  Chrome binary in its own window, not a webview embedded in the app.
- **CDP against the parent's *daily* Chrome.** Rejected — relaunching an
  everyday browser with a debug flag is a hostile install step and a standing
  local hole for every other tab open in it. A *dedicated, single-purpose*
  profile used for nothing else has neither problem.
- **Ask the district to allowlist the extension.** Genuinely the cleanest
  long-term answer, and there's an open conversation with them already
  (`docs/DISTRICT_COMMUNICATION_REPORT.md`). But it makes the tool
  undistributable to any other family, and it puts a dependency on district
  goodwill in the critical path. Worth asking for; not worth waiting on.
- **Loopback HTTP instead of native messaging.** Simpler to build — no host
  manifest, no per-OS install paths — but it opens a port any local process
  can reach, and pairing it properly (shared secret + origin check) claws
  back most of the simplicity it bought. Native messaging authenticates for
  free: Chrome only launches hosts whose manifest names the extension ID.

---

## The capture pipeline

### Trigger

**A capture checklist is the actual UX**, and what it means depends on the
tier:

- **Tier 0**: tracks which saved files have landed in the watched folder and
  shows what's still missing.
- **Tier 1**: the parent works through the list in the Schoolwork profile by
  hand — each URL match auto-captures, so it's a click-through, not a
  save-as. The checklist ticks off each source as its capture arrives over
  native messaging.
- **Tier 2** (if built): the parent clicks "Run a pass" once; the app drives
  the same profile through the whole list and the checklist ticks itself off
  with no further clicking. If a page comes back as a login wall, the pass
  pauses and asks the parent to sign in, then resumes.

The allowlist of capture-worthy URL patterns ships with Classroom and Genesis
entries and is user-editable either way.

### Settle detection

Classroom paints progressively and lazy-loads as you scroll. Capturing on
`load` gets a skeleton. The extension's content script runs a
`MutationObserver` quiet-period check and captures once the subtree has been
still for ~750ms, with a hard ceiling (~10s) so a page with a permanently
spinning widget still yields something. It should also scroll the page toward
the bottom before settling, since Classroom defers content until it comes
into view — a capture that never scrolled will quietly miss older stream
items. Under Tier 2's self-driving, this happens automatically after each
navigation; under plain Tier 1, the extension re-checks settle state as the
parent scrolls, so a manual scroll-and-pause also (re-)triggers a capture.
Tier 0 inherits whatever the parent had actually scrolled into view when they
hit Ctrl+S — worth telling them that in the UI.

### Reduction — the part that matters most

**Do not ship raw HTML.** The saved reference capture
(`../englishClassroomstream.html`) is 1.8MB plus a `_files/` folder, and
nearly all of it is Google's obfuscated class-name soup, inline base64, and
framework noise. Reduce in-page, before anything leaves the browser.

Strip: `<script>`, `<style>`, `<svg>`, `<noscript>`, comments, inline
`data:` URIs, and every class attribute.

**Keep — and this is the non-obvious part — the accessibility attributes.**
In the real Classroom capture, `aria-label` carries the entire semantic
payload that the visible text does not:

```
aria-label="Assignment: Quiz: The Americas and Europe Before 1492, due Tomorrow"
aria-label="Assignment: C1L4 Segment Addition Postulate Notes, due Friday"
aria-label="Assignment: Activities Fair, due Tomorrow"
```

A generic HTML-to-text/readability pass throws those away and takes the due
dates with them. The reducer must preserve `aria-label`, `role`, `title`,
`href`, `datetime`, and `data-*` on every retained node. This is the same
class of bug as schoolz's `zoom_out_map` incident — a reducer quietly dropping
the only field that mattered, with no error anywhere.

Anchor on `aria-label` / `role` / URL shape / visible text. **Never** on
Google's CSS class names; those are generated and will churn.

### Capture envelope

Every capture carries, alongside the reduced text:

| Field | Why |
|---|---|
| `captured_at` (absolute, with offset) | "due Tomorrow" is meaningless without it |
| `timezone` | resolve relative dates in the school's real local time |
| `source_url` | which class, which view, which adapter |
| `account_index` (`/u/0/`, `/u/1/`) | **which child** — two kids merge into one mess without it |
| `adapter` + `adapter_version` | so a reducer change can trigger re-extraction |
| `char_count` | feeds the low-confidence check below |

Relative dates get resolved **deterministically in the app** from
`captured_at` + `timezone` — not by asking the model what "Tomorrow" means.
Same lesson as schoolz's date pipeline: naive datetimes treated as UTC shifted
every all-day event back a day.

---

## Extraction

Port schoolz's proven `content_extractor.py` shape rather than re-deriving it:

- **Structured tool-use call with an explicit schema**, `temperature=0`.
- **`items` declared first in the schema.** Schoolz lost an entire 37-block
  newsletter to `stop_reason: "max_tokens"` because `items` came last and the
  model got cut off before writing any. Generate the important part first.
- **Log and surface `stop_reason == "max_tokens"`** rather than silently
  returning a short list.
- **Don't trust model booleans.** Infer `is_all_day`-style flags from the data
  (does the resolved date carry a time component?), not from a field the model
  fills in unreliably.
- **Backfill links programmatically.** If the model drops a `link_url` that's
  sitting right there in the source node, restore it from the capture. Don't
  fight the model over something verifiable.

Extracted shape, roughly: `title`, `course`, `type`
(`assignment` / `quiz` / `material` / `announcement`), `due_at`, `status`
(`assigned` / `missing` / `submitted` / `graded`), `points`,
`teacher_note`, `link_url`, `attachments[]`.

**Attachments are links, not fetches.** A Drive attachment needs the child's
auth to read; the app records title + URL and stops. If the parent wants the
contents, they open it — and the extension captures *that* page too, through
the same mechanism. The recursion is free.

---

## Identity and dedup

The same assignment shows up on the To-do page, on its class stream, and
possibly in Genesis. Without stable identity the consolidated list becomes a
pile of near-duplicates — schoolz's "so many 'first day of school' events"
problem, again.

- **Prefer the real ID from the DOM/URL.** Classroom item links are shaped
  like `/c/<courseId>/a/<itemId>/details`; that `itemId` is the identity.
  This is schoolz's `external_uid` pattern.
- **Fall back to a content hash** of `(course, normalized title, due date)`
  only when no ID is recoverable.
- **Supersede, don't duplicate.** A recapture with a changed due date marks
  the old row `is_current = false` and links forward, rather than deleting.
  The parent can then see "this moved" instead of silently getting a
  different answer than they got yesterday.
- **Cross-source claiming.** Genesis and Classroom describing the same
  assessment should collapse to one row, with Genesis's grade attached to
  Classroom's assignment. Same claiming behavior as the district ICS feed
  taking over a newsletter-sourced event.

---

## Data model (sketch)

```
child          id, display_name, account_index, color
source         id, child_id, adapter, url, label, last_captured_at, last_status
capture        id, source_id, captured_at, timezone, adapter_version,
               reduced_text, char_count, extraction_status
work_item      id, child_id, course, external_uid, title, type, due_at,
               status, points, link_url, is_current, superseded_by,
               first_seen_at, last_seen_at
attachment     id, work_item_id, title, url, kind
```

Raw `reduced_text` is retained (encrypted at rest, auto-purged on a
user-set window, default ~30 days) specifically so a reducer or prompt
improvement can **re-extract without asking the parent to re-browse
everything**. Schoolz needed exactly this when the `zoom_out_map` fix landed
and 25 already-stored blocks had to be re-run.

---

## The UI

Four screens. The first one is the product; the rest exist to serve it.

1. **Due** — one chronological list across every child and class. Filter by
   child (using the per-child color, same convention as schoolz's school
   ribbon). Missing/overdue pinned at the top and visually distinct. This is
   the screen that justifies the whole app.
2. **Capture checklist** — what's fresh, what's stale, what's never been
   captured. Under Tier 1, this is a list of bookmarks with status dots the
   parent works through in the Schoolwork profile; under Tier 2 (if built),
   a "Run a pass" button drives it end to end.
3. **Item detail** — the assignment, its teacher note, its attachments, its
   history (moved dates, status changes), and a link back to the real page.
4. **Settings** — children/accounts, allowlist, retention window, API key.

**Staleness rendering is a first-class UI element, not a footnote.** Every
source carries a visible age, and anything past a threshold (say 48h) is
rendered as explicitly unknown rather than quietly showing old data — "Math:
not captured since Tuesday" beats an empty list that reads as "nothing due."
This is the single biggest failure mode of an attended-capture design.

---

## Privacy and security posture

- Local-only storage; no telemetry; no crash reporting that could carry page
  content. (Note the contrast with schoolz, which *does* run Faro RUM — the
  data here is categorically different and shouldn't inherit that decision.)
- SQLite encrypted at rest with an OS-keychain-held key.
- The Anthropic API key lives in the OS keychain, never in the extension.
- **The Schoolwork Chrome profile holds a live Google session.** Under Tier 1
  alone it's a normal Chrome profile the parent created through
  `chrome://settings`, living wherever Chrome's own profile directory is
  (`.../User Data/Profile N`) — the app has no say over that location, so
  check whether that path falls under any whole-`AppData`/whole-home backup
  or sync tool already running on the machine (this repo's own workspace
  sits in OneDrive; that's the kind of blanket sync that would silently catch
  it). If Tier 2 gets built, the app *does* choose the `--user-data-dir`, and
  should point it somewhere explicitly excluded from any such sync. Either
  way, "sign out of the Schoolwork profile" is the equivalent of revoking
  access — document it as a real, named step, not an assumption.
- Only reduced text crosses the network. Never cookies, never raw HTML with
  embedded session artifacts, never attachment bytes.
- A visible "what was captured" log the parent can read and purge, per item.
- Worth a look before any distribution: this is a child's education record,
  and even though it's the parent's own copy on the parent's own machine, a
  tool that aggregates it invites FERPA-adjacent questions the moment it
  becomes something other people install.

---

## Adapters

An adapter is: a URL matcher, a reducer, an expected-shape assertion, and a
fixture. Two to start. **Resist building a general scraper** — generality is
what makes reducers silently wrong.

### Google Classroom

- **The To-do / "not turned in" aggregate view is the highest-value single
  page** — one capture covers every class. Per-class streams are the
  follow-up, for teacher notes and context the aggregate view omits.
- `/u/<n>/` in the URL is the account index → the child. Capture it.
- Expected shape assertion: ≥1 node whose `aria-label` starts with
  `Assignment:` / `Material:` / `Announcement`.

### Genesis

- Expect a legacy frames-and-tables layout; `all_frames: true` and per-frame
  capture, merged by frame order.
- Short session timeouts are likely — the checklist should let the parent
  recapture a single source without redoing the whole pass.
- Grades and assignment status are the payload here; Classroom is the better
  source for the work itself.

---

## Failure modes, and how each one surfaces

Silent failure is the enemy — every schoolz bug worth remembering was a
silent one. Each of these must produce a visible state, never an empty list:

| Failure | Surfaces as |
|---|---|
| Reducer returns suspiciously little text | Capture flagged **low confidence**, extraction still runs, banner on the item list |
| Expected-shape assertion fails (Google changed the DOM) | Source marked **adapter may be broken**, with the raw capture kept for inspection |
| Extraction hit `max_tokens` | Capture marked **partial**, explicit "some items may be missing" |
| Parent wasn't logged in / hit a login wall | Capture rejected before storage — a login page must never overwrite good data with nothing |
| Source not captured in N days | **Stale** badge, excluded from "nothing due" claims |

That fourth row deserves emphasis: a capture that lands on a login redirect
looks structurally valid and contains zero assignments. Detect it explicitly
(login-form heuristics + the shape assertion) and refuse to store it.

---

## Explicitly out of scope

- **Automated login, and unattended refresh.** Non-negotiable — it's what
  makes the approach work at all. Note the boundary if Tier 2 gets built:
  navigating an *already-authenticated* session between known URLs is in
  scope (it's a bookmark), while anything that authenticates, submits a form,
  or runs with no human present is not. A pass happens because a parent
  clicked "Run a pass," never on a timer.
- Turning work in, messaging teachers, or any write action. Read-only.
- ClassDojo / Remind / Teaching Strategies. Same technique would generalize,
  but each is another adapter; prove the model on two first.
- Merging any of this into the schoolz backend. Schoolz is public, no-login,
  centrally admin-managed; this is personal and credentialed. Keeping them
  separate keeps schoolz's access model honest.

---

## Build order

Reordered around the constraint: **every step that can be de-risked without
browser integration now comes first**, and the Verification protocol runs
before any Tier 1 code gets written at all.

1. **Run the Verification protocol** (above). Costs 15 minutes, and its
   result decides whether steps 4+ target Tier 1 or stop at Tier 0.
2. **Tier 0 ingestion + the reducer**, run against the capture already on
   disk (`../englishClassroomstream.html`). No browser work, no Claude call —
   just prove the reducer keeps the `aria-label` payload and drops the 1.8MB
   of noise. This is a fixture-driven unit test, the same way the
   transportation parsers were built.
3. **Extraction → `work_item` rows → the Due list** for one child. At this
   point it's a working product with a Ctrl+S step, independent of whether
   verification passed.
4. **Identity, dedup, supersede.** Then multi-class and multi-child.
5. **Tier 1 extension**, if verification passed: build the Schoolwork
   profile + extension + native host, capture one Classroom page by hand,
   confirm it reaches the desktop app.
6. **Capture checklist + staleness UI**, tracking whichever tiers are live.
7. **Genesis adapter** (capture a real page first; see Open questions).
8. **Tier 2 self-driving navigation** — the one genuinely optional step;
   build only once Tier 1 has been lived with and manual click-through has
   become the actual friction point.
9. **Re-extraction from stored captures** — needed the first time a reducer
   bug is found, and one will be.

---

## Open questions

- **Result of the Verification protocol.** Everything above is written
  assuming it passes; if it doesn't, this document's primary path needs to be
  rewritten around Tier 0 alone, or around asking the district to allowlist
  the extension.
- **One Schoolwork profile per child, or one shared profile with multiple
  `/u/N/` accounts?** A second child means either a second dedicated profile
  (cleanest — one extension install, one session, no ambiguity) or adding her
  sibling as `/u/1/` inside the same one. If it's the latter, `account_index`
  in the capture envelope is what maps a capture to a child, and getting it
  wrong silently merges two kids' work into one list.
- **Verify the Classroom To-do path** and whether it reliably renders every
  class, or silently caps.
- **Genesis's actual DOM** — frames or not? Grab one real capture before
  designing the adapter, the way the transportation parsers were built
  against saved fixtures.
- **Retention default**: 30 days of raw captures is a guess. Longer helps
  re-extraction; shorter is better hygiene for this data.
- **Multiple parents / devices**: two parents each running their own copy get
  two divergent local stores with no sync. Acceptable? It's the direct cost
  of principle 3.
