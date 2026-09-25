# "Explain it differently": videos from approved channels (design)

Design only. Nothing here is built yet. It adds to the Kids view v2 /
Focus task sheet (`docs/KIDS_VIEW_V2_DESIGN.md` §7,
`frontend/focus/src/components/TaskModal.tsx`) and uses the same
title-and-course-only privacy rule as the tier-A suggestion.

## The problem

The sheet already covers three kinds of stuck:

| Stuck because… | Existing answer |
|---|---|
| I don't know what to do first | **How to start** (tier A, `AssignmentSuggestion`) |
| The assignment is unclear | **Ask the teacher** (`help_requests.py`: `what_to_hand_in`, `cant_find`, `how_to_start`) |
| I didn't get the **lesson** itself | **Ask the teacher** only (`dont_understand`, `dont_remember`) |

The last row is the gap. A teacher's reply comes tomorrow at the
earliest, and the student is sitting at the kitchen table tonight. What
helps right now is hearing the same idea explained by someone else, in
a different way. Good explainer videos exist, but sending a kid to
YouTube search sends them into the recommendations feed, which is the
worst place to send an ADHD brain that's already avoiding the work.

So: **up to three short videos, only from channels an admin approved,
picked for this assignment's topic, played inside the sheet.**

## Rules (the parts that aren't negotiable)

1. **Approved channels only, checked in code, not by the prompt.** Every
   video we show is built from a `video_id` that is in our own index,
   belongs to a channel that's approved *and enabled right now*, and
   isn't individually blocked. This is checked **every time the picks
   are read**, not just when they're generated. Turning off a channel
   removes its videos from every cached pick immediately. The model
   chooses from a numbered list of candidates and returns list numbers.
   It never writes a URL or a video id (same idea as `_find_link()` and
   `_KNOWN_PORTAL_URLS`).
2. **Only the title and course name ever reach the model**, the same as
   tier A. Picks are cached and shared by every student in the course,
   so nothing personal can go into them.
3. **Only on request.** Nothing is picked when a capture is imported or
   on a schedule. The only scheduled work is re-indexing the channel
   catalogs, which is public data and has nothing to do with any
   student.
4. **We don't record who watched what.** Same reasoning as
   `HelpRequest`, which doesn't store the email body. A parent seeing
   "watched 4 videos about the unit circle" is surveillance. Knowing
   that three videos were offered is not useful to anyone.
5. **It follows the Focus view rules.** At most 3 videos. Nothing plays
   automatically. The section is collapsed until tapped. Nothing is
   added to the dashboard card; this lives only in the sheet.

## 1. Data model

```
ApprovedVideoChannel                      -- admin-managed, global
  id
  youtube_channel_id    UNIQUE            -- "UC…", resolved when added, never typed in
  handle                                  -- "@khanacademy", for display + channel search links
  title, thumbnail_url                    -- from channels.list
  uploads_playlist_id                     -- contentDetails.relatedPlaylists.uploads
  subjects: list[str]                     -- closed set, see §3
  levels:   list[str]                     -- "middle" | "high" (School.school_type values)
  notes                                   -- why it was approved; shown only to admins
  enabled: bool
  approved_by_user_id → users (SET NULL)
  approved_at, last_indexed_at, video_count
  index_job_id → scheduled_jobs (SET NULL)

ChannelVideo                              -- the local index; public data only
  youtube_video_id      UNIQUE
  channel_id → approved_video_channels (CASCADE)
  title, description (first ~1000 chars), published_at
  duration_seconds                        -- from videos.list contentDetails
  is_short: bool                          -- duration ≤ 60s; left out of results
  blocked: bool                           -- admin removed this one video, channel stays approved
  search_vector tsvector GENERATED        -- title weighted A, description weighted C; GIN index

AssignmentVideoPick                       -- shared cache, like AssignmentSuggestion
  course_code, normalized_title           UNIQUE together
  subject                                 -- what the model classified the course as
  topic_query                             -- the phrase we searched with; admins can see it
  video_ids: list[str]                    -- in order, up to 3; may be empty
  declined: bool                          -- the title was too vague to pick a topic
  channel_set_hash                        -- which enabled channels existed when this was picked
  model, generated_at
```

**The pick is keyed on `course_code` without the section**, unlike
`AssignmentSuggestion`. Every section of the same course follows the
same curriculum, so "Algebra 2 / Graphing Rational Functions" has the
same right videos in section 1 and section 4. Dropping the section lets
more families share one cached pick. Items whose course has no district
code fall back to `course_key()`'s `slug:`/`name:` form, which never had
a section anyway.

**When a pick goes stale:** `channel_set_hash` is a hash of the enabled
channel ids tagged with the pick's subject. If an admin approves a new
Chemistry channel, every Chemistry pick's hash stops matching, and each
one is re-picked the next time someone opens it. Nothing is
bulk-recomputed. Removing a channel doesn't need this, because rule 1
already filters its videos out at read time.

## 2. Indexing approved channels (no search API)

YouTube's `search.list` costs 100 quota units per call and takes only
one `channelId` at a time. The default 10,000 units/day would allow
about 100 searches a day, spread across every channel. That's not
enough, so we never call it. Instead we copy each approved channel's
catalog into our own database and search locally:

- `channels.list?forHandle=` or `?id=` → channel id, uploads playlist (1 unit)
- `playlistItems.list` over the uploads playlist, 50 per page (1 unit/page)
- `videos.list?part=contentDetails` for durations, 50 ids per call (1 unit)

Khan Academy has about 10k uploads, so indexing it costs about 400
units once. Weekly refreshes stop paging when they reach a video that's
already in the index (the uploads playlist lists newest first), so a
refresh usually costs 1–2 units. Needs one env var, `YOUTUBE_API_KEY`
(an API key, not OAuth, because everything read is public). Add it to
`docs/ENV_SETUP.md`.

This is a new scheduler job kind, **`video_channel.index`**, one per
channel. Adding a channel creates the job (`_ensure_video_channel_job`,
same pattern as `_ensure_*_job`) and runs it once right away.
Schedule: weekly, `0 5 * * 1`. It runs through plain `httpx` against
the API and never touches the scraper or Playwright, so it doesn't add
to the 12h Chromium burst. The run is a `WARNING` if the channel
returns zero videos (it was deleted, renamed, or made private). Videos
that disappear from the playlist are deleted from the index, the same
way the HS rotation parser deletes rows that vanish from its PDF.

## 3. Subjects and levels

Channels and picks use the same closed list of subjects:

`math`, `biology`, `chemistry`, `physics`, `earth_science`,
`english`, `history`, `civics_econ`, `world_language`,
`computer_science`, `art_music`, `health`

- A **channel** gets subjects from the admin, and can have several
  (Khan Academy gets almost all of them; Amoeba Sisters gets `biology`
  only).
- A **course** gets its subject from the model, in the same call that
  picks the topic (§4). It sees the course name and must choose from
  this list or say `other`. A course marked `other` gets no videos,
  which is better than a wrong guess.
- A **level** comes from the student's `School.school_type` and is
  applied at read time, so the shared pick doesn't depend on who opens
  it. A channel tagged only `high` never appears for a middle-school
  student. If filtering leaves no videos, the section shows its
  fallback (§5) and no second pick is made.

## 4. Picking the videos (three steps; the model is used twice)

**Step 1: turn the title into a topic.** Haiku, `temperature=0`, forced
tool use. The input is the course name and the assignment title, and
nothing else. The output is:

```
{ subject: <enum|other>, clear_enough: bool,
  topic_query: "graphing rational functions asymptotes" }
```

The prompt matches tier A's: if the title doesn't say what the work is
about ("Classwork 9/12", "Do Now", "Untitled Formative 817"), set
`clear_enough=false`. Don't guess. That result is stored as `declined`
so the same vague title isn't sent to the model again. `topic_query`
must describe the *concept*, not restate the assignment: "Lab 4:
Stoichiometry Practice" should come out as "stoichiometry mole ratios",
not "lab 4". This is the one place a model helps, because titles are
written in teacher shorthand and a keyword search on the raw title
doesn't find anything.

**Step 2: search our own index, no model.** A Postgres full-text query
over `ChannelVideo.search_vector`
(`websearch_to_tsquery('english', topic_query)`), limited to enabled
channels tagged with the subject and to videos that aren't blocked and
aren't Shorts. Take the top 15 by `ts_rank`, with a small bonus for
videos between 3 and 15 minutes. If nothing matches, store an empty
pick and go straight to the fallback. Don't retry with a looser query.

**Step 3: choose from the candidates.** Haiku again. It gets the
course, the title, and a **numbered list** of the 15 candidates (video
title, channel, duration). It returns up to 3 numbers, most useful
first, or an empty list if none of them really explain this topic. The
code drops any number that isn't on the list and removes duplicates;
the model never sees or returns a video id. Leave step 3 out and you'd
get whatever has the most matching keywords: a 40-minute AP review
stream ranked above a 6-minute explainer, or a video whose title only
happens to share a word.

When step 3 fails (API error or `max_tokens`), use the top 3 results
from step 2 as they are, and record a `record_parse_issue` so admins
can see it happened. The student still gets something from an approved
channel.

## 5. API

```
POST /students/{id}/bucket3/videos/{work_item_id}
  → { videos: [{video_id, title, channel_title, duration_seconds, thumbnail_url}],
      declined: bool,
      fallback: [{channel_title, search_url}] }
```

- Same access check as the other bucket3 routes (`_get_own_student`:
  the guardian or the student).
- Looks up the cached pick by `(course_code, normalized_title)`. If
  there's no pick, or its `channel_set_hash` is stale, it runs §4 and
  stores the result.
- It **always** runs rule 1's filter and the level filter before
  responding, whether or not the pick came from the cache.
- **`fallback`** is a list of links, one per matching approved channel
  (at most 3), to that channel's own search page:
  `https://www.youtube.com/@handle/search?query=<topic_query>`. It
  appears when there are no videos, when the title was declined, and
  as a quieter "more from these channels" link under real results. The
  link opens a search *within one approved channel*, so it can't lead
  anywhere else.
- When the title was declined, the fallback also needs a topic, so the
  sheet shows a single text field: *"What was the lesson about?"*
  Whatever the student types goes to
  `GET /students/{id}/bucket3/videos/search?q=`, which runs **step 2
  only**: a plain database search, no model call, nothing stored, and
  it caches nothing. The typed words are the student's own and never
  reach the model or a shared cache.

Admin (`require_admin`, lives under the `/admin` tabs, like Scans):

```
GET/POST/PATCH/DELETE /video-channels          -- POST takes a URL or @handle, resolves it
POST /video-channels/{id}/reindex              -- run-now
GET  /video-channels/{id}/videos?q=            -- browse + block/unblock single videos
POST /video-channels/preview                   -- {course_name, title} → the full §4 pipeline,
                                                  shows topic_query + candidates + picks, saves nothing
DELETE /video-picks?subject=                   -- clear cached picks after re-tagging channels
```

`preview` works like local events' **Test fetch**: an admin approving a
new channel can type "Chemistry H / Lab 4: Stoichiometry" and see what
students would get, before and after.

## 6. The sheet (Focus `TaskModal`)

A new section, **"Explain it differently"**, placed right under **How
to start** and above **Ask the teacher**. That's the order a stuck kid
goes through: try to start, hear it again, then ask. It follows the
`Starter` component's collapsed/expanded pattern:

- **Collapsed** (default): one button, *"Watch someone explain it"*.
  Tapping it calls the API.
- **Results**: up to 3 rows showing thumbnail, title, channel, and
  duration (*"6 min"*). Tapping a row plays it **in the sheet** in a
  `youtube-nocookie.com` embed with `autoplay=0`, `rel=0`
  (recommendations only from the same channel), and
  `modestbranding=1`. There is no "up next", no sidebar, and no feed.
  Under the player is a small *"Open in YouTube"* link for the student
  who wants captions or casting. It's available but not encouraged.
- **Declined**: *"The title doesn't say what the lesson was. What was it
  about?"* plus the text field (§5). No model call happens there.
- **Nothing found**: the channel-search fallback links, and nothing
  else.

It also connects to **Ask the teacher**. After the student picks
`dont_understand` or `dont_remember` and the email draft appears,
show one line under it: *"While you wait for a reply, want to hear it
explained another way?"* That line expands this same section. The
teacher still hears about it, since the email is the first thing shown.
The video is something to do while waiting for the reply, not
something that replaces asking.

The main frontend's `KidsDetailPage` gets the same section, because a
guardian sitting next to the kid is the other half of the use case.

## 7. Admin tab: Videos

A new tab in `/admin`, next to Newsletters / Scans / Import-export,
built with the admin UI kit (DataTable + Modal):

- **Channel table**: thumbnail, title, handle, subject badges, level
  badges, video count, last indexed, enabled switch. Row actions:
  edit, reindex, browse videos, delete (with ConfirmDialog; deleting a
  channel removes its indexed videos).
- **Add channel** modal: paste a channel URL or `@handle` → resolve it
  → show the channel's title, avatar, and subscriber count so the admin
  can confirm it's the right channel before saving → choose subjects
  and levels → add a note on why it's approved. Required: an approval
  without a reason is how a list goes bad over time.
- **Browse videos**: a search box over one channel's index, with a
  per-row *Block* switch, for the single off-topic, outdated, or
  sponsored video on an otherwise good channel.
- **Preview** panel (§5).

Check the Katalyst template for a "media library" or "catalog" list
pattern before building the channel table (CLAUDE.md, *UI reference
template*).

## 8. Suggested starting list (for admins to approve, not a seed migration)

Admins approve channels, so this isn't hard-coded. A starter list to
look through: Khan Academy, CrashCourse, The Organic Chemistry Tutor,
Professor Dave Explains, Amoeba Sisters, Bozeman Science, TED-Ed,
Math Antics (middle), Heimler's History (high), Tyler DeWitt,
Numberphile (enrichment, not tagged for coursework). Each one needs a
person to decide whether to approve it, choose its subjects, and write
the reason.

## 9. Deliberately not doing

- **Searching all of YouTube**, even as a fallback. Every video shown
  must come from an approved channel.
- **Recording which videos were watched**, or anything per student
  beyond what's already there. There is no watch history, no
  "helpful?" rating per student in v1, and no guardian notification.
- **Transcripts or captions as search input.** Titles and descriptions
  are enough to start with. Transcripts would mean scraping, since
  there's no API for them with an API key, and scraping YouTube is the
  kind of thing that got our IP CAPTCHA'd before.
- **Teacher-provided videos.** When a teacher posts a video in
  Classroom, it's already in the item's attachments. This feature is
  for the case where the teacher's own explanation didn't work.
- **Picking videos in the background for everything imported.** That
  wastes quota and model calls on assignments nobody got stuck on
  (same reasoning as tier A).

## 10. Build order

1. Models + Alembic migration (`ApprovedVideoChannel`, `ChannelVideo`
   with its generated tsvector + GIN index, `AssignmentVideoPick`).
2. `services/youtube_index.py` + the `video_channel.index` job kind,
   with fixtures of real `channels.list`/`playlistItems.list`/
   `videos.list` responses in `tests/fixtures/`. Add the env var to
   `docs/ENV_SETUP.md`.
3. Admin CRUD + Videos tab (table, add modal, browse/block). Admins
   can start approving and indexing channels before any student sees
   anything.
4. `services/video_picks.py` (§4) + the preview endpoint. Test it with
   real prod titles until the topic queries look right, the same way
   the `staff_roles` keywords were tuned against real titles.
5. The student endpoint + read-time filter. Unit-test rule 1
   specifically: a pick that mentions a now-disabled channel or a
   blocked video must return without it.
6. Focus `TaskModal` section + the Ask-the-teacher tie-in, then
   `KidsDetailPage`.
7. A CLAUDE.md entry under *Domain model*, covering the privacy rule,
   the section-free key, and why search.list is never used.

## Open questions

- **Play in the sheet vs. open in YouTube.** This design plays videos
  in the sheet, since keeping the student out of the YouTube feed is
  most of the point. The embed does load Google's player: nocookie
  means no cookies until play, but there's still a request to Google.
  `/chcomms` promises no tracking by *schoolz*; confirm this fits
  that promise, or show a "plays from YouTube" note before the first
  play.
- **Shorts.** They're excluded to start with. Some channels post good
  60-second concept explainers; we could allow Shorts per channel if
  an admin wants them.
- **Elementary.** Out of scope, like the rest of Kids view v2, until
  there's elementary Classroom data.
