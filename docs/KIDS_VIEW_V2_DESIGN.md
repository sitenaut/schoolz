# Kids view v2 — parent + student coursework dashboard (design)

Design only. Nothing here is built yet. Written for Sonnet to implement in
phases (see "Build order" at the end). Builds on top of the bucket 3
import pipeline that already exists (`backend/services/bucket3_extract.py`,
`backend/routers/bucket3.py`, `frontend/src/pages/KidsPage.tsx` +
`KidsDetailPage.tsx`) — this document does not replace that pipeline, it
adds student accounts, actionable state, teacher-email links, and two
tiers of AI-assisted suggestions on top of the data it already produces.

## Scope

**High school and middle school only, for now.** Both have the
multi-period, multi-subject structure (`ChildScheduleBlock` periods,
`ChildWorkItem`/`ChildGradeEntry` per course) this whole design is built
around. Elementary and preschool don't have that shape yet in the data
this app collects (no per-period Genesis schedule captures have been
attempted for them, and their Classroom/Genesis usage, if any, is
unverified) — explicitly out of scope until that's confirmed against a
real capture, same "verify one real capture first" rule the extraction
layer has followed throughout.

## Who sees what, and why this needs student accounts

Today only a guardian can see bucket3 data (`_get_own_student` in
`routers/bucket3.py` requires a `GuardianStudentLink`). The ask here is
explicit: **the student should see the same data the parent sees** — same
schedule, same due/missing/done list, same grades — not a separate
kid-facing app with its own copy of anything.

This is the previously-deferred `Student.user_id` column CLAUDE.md flagged
("Not built yet ... add later once there's real per-student data to
attach it to" — that data now exists). Concretely:

- `Student.user_id` (nullable, unique FK to `users.id`). A student who has
  a schoolz login IS this column pointing at their `User` row — not a
  separate account type, not a guardian relationship.
- A **guardian-initiated invite**, mirroring `GuardianInvite`'s existing
  shape but for a different relationship (this grants *being* the
  student, not being a guardian of one):
  ```
  StudentAccountInvite
    id, student_id, invited_by_user_id (must already be a guardian of
    student_id), invitee_email, token, status ("pending"|"accepted"|
    "revoked"), created_at, expires_at, accepted_by_user_id, accepted_at
  ```
  - `POST /students/{id}/account-invites` — guardian-only (existing
    `_get_own_student`-style check), creates the invite. Local mode
    returns the accept link directly in the response (no mailer, same
    as `GuardianInvite`'s and the password-reset flow's local-mode
    pattern) — real deployments send it.
  - `GET /student-account-invites/{token}` — public preview, first name +
    last initial only (same privacy rule as `GET /invites/{token}`).
  - `POST /student-account-invites/{token}/accept` — creates a new `User`
    (registration fields: email pre-filled from the invite, username,
    password) and sets `Student.user_id`. Refuses if `Student.user_id` is
    already set (one student account per student, not one per invite
    accepted).
- New auth dependency, `get_current_student_or_guardian(student_id, user)`,
  used everywhere bucket3 routes currently call `_get_own_student`:
  passes if the caller has a `GuardianStudentLink` **or** if
  `student.user_id == user.id`. One access check, two ways to satisfy it.
- Password reset: already generic per-`User` (local mode's
  `/auth/forgot-password` / Supabase's `resetPasswordForEmail`) — nothing
  student-specific to build, just confirm the flow doesn't assume
  `is_admin`/guardian status anywhere (it shouldn't; check on
  implementation).
- **Never build**: a parent "logging in as" their child, or a child
  self-registering without an invite. The invite is the only path to a
  student account, and only an existing guardian can create one.

## 1. "Right now" — today's period in context

The existing Today page (`services/school_today.py`) shows a school's
own bell schedule. This is the same idea, scoped to one child's *actual*
schedule (`ChildScheduleBlock` source="daily" for today + the
`ChildDayCycle` cycle label), not the school-wide one.

- Port the current-period resolution schoolz already has
  (`services/bell_schedule.py:current_period` — given a list of
  `{name, start, end}` and a now-timestamp, finds the containing period,
  minutes in/left, and what's next) against the child's own daily blocks
  instead of `School.bell_periods`. Same function, different input list —
  do not fork a second implementation of "what period is it right now."
- `GET /students/{id}/bucket3/right-now` →
  ```
  { cycle_label: str | null,
    current: { period, course_name, teacher, room, time_start, time_end,
               minutes_in, minutes_left } | null,
    next: { period, course_name, time_start } | null,
    schedule_date: str | null,   // which day's schedule this is, for staleness display
    stale: bool }                // schedule_date isn't today - show it, don't hide it
  ```
- `stale: true` (schedule imported but not for today) must render as an
  explicit "last captured for {date}" state, never silently show
  yesterday's period as if it were current — this is the same lesson as
  the extension's own "Missing X since Tuesday" staleness rule.
- No daily schedule imported at all → `current: null, next: null`, not an
  error. The UI's empty state points at "capture a Genesis student
  summary page and import it."

## 2. Due / Missing / Done

`ChildWorkItem` today has `due_date` (resolved) and `status` (currently
always `null` — nothing populates it). Two additions:

**a) Extract real status from Classroom's own text**, where it says so.
Confirmed real shapes seen in captures so far: a classwork-tab entry can
show `"Completed"` immediately before its type line (a different shape
than the button+Due-line pattern already parsed — verify against a fresh
capture before writing the regex, this wasn't confirmed as a general
pattern, only spotted once). Extend `extract_classroom_work_items` to
capture whichever of `Completed` / `Missing` / `Turned in` / `Assigned` /
`Late` appears in the item's block, same bounded-lookahead style already
used for `Due`/type/id. Store as `ChildWorkItem.status` (column already
exists, just unpopulated).

**b) A guardian/student-driven "done" override**, independent of what
Classroom itself claims (Classroom's own status can lag, and a parent
marking something done in schoolz shouldn't require Classroom to agree
first):

```
ChildWorkItemProgress
  id, student_id, work_item_id (FK child_work_items.id, cascade),
  done: bool, marked_by_user_id, updated_at
UNIQUE(student_id, work_item_id)
```

- `POST /students/{id}/bucket3/workitems/{work_item_id}/complete
  {done: bool}` — either a guardian or the student account may toggle it;
  it's one shared row, last write wins, `marked_by_user_id` is kept so the
  UI can say "marked done by Ryan" vs "marked done by a parent" — visible,
  never silent about who changed shared state.
- Derived display category (computed at read time, not stored):
  - **Done** = `ChildWorkItemProgress.done` is true, OR Classroom's own
    `status` says turned-in/completed/graded, OR a matched Genesis grade
    exists with a real score (not `Missing`/`Exempt`).
  - **Missing** = `due_date` is in the past, not Done, and either
    Classroom's own `status == "Missing"` or no submission evidence at
    all.
  - **Due** = `due_date` is today or in the future, not Done.
  - Items with no `due_date` at all (materials, most announcements)
    aren't Due/Missing/Done — they're reference content, shown separately
    (see Announcements below), never counted toward progress.

## 3. Announcements

`extract_classroom_work_items`' shape-A branch already recognizes
`item_type == "announcement"` (the aria-label prefix `Announcement:` was
part of the original three-prefix check) — announcements are already
landing in `ChildWorkItem`, just mixed in with assignments/materials with
no way to filter to just them, and with no "posted" timestamp (only
`due_date`, which announcements don't have).

- Add `ChildWorkItem.posted_raw` / `posted_date` (same
  raw-text-plus-resolved-date pattern as `due_raw`/`due_date`) — Classroom
  posts carry a `Created\n<date>` line near the item (confirmed real:
  `"Created\nSep 11"` in captures already gathered) — extend the parser
  to capture it the same bounded-lookahead way as `Due`.
- `GET /students/{id}/bucket3/announcements` — `item_type == "announcement"`,
  ordered by `posted_date` descending (falls back to `last_seen_at` when
  no posted date parsed). Collapsed by default in the UI (see Focused
  View) — informational, not actionable, shouldn't compete for attention
  with the to-do list.

## 4. Per-course progress (student's own framing)

The student's ask is specific: *"progress per class based on assignments
available vs missing, past due, and grades less than 50%."* One rollup
endpoint, computed from data that already exists:

`GET /students/{id}/bucket3/progress` →
```
[{ course_name, course_code, course_section,
   total, done, missing, due_soon,
   completion_pct,               // done / (done+missing+due), excludes no-due-date items
   low_grade_entries: [ {title, percent} ]  // this course's Genesis entries with percent < 50
}]
```

- `low_grade_entries` is a flag, not a calculation. **Do not** implement
  the student's "max 70% after makeup" math — that's a
  teacher/district-specific policy this app has no authoritative source
  for. Surface it as "below 50% — ask your teacher about makeup work,"
  full stop. Same restraint as the marking-period discrepancy check:
  report the fact, don't guess the policy.
- Grouped by `(course_code, course_section)` the same way `ChildCourseGrade`
  already is, so a course with no Genesis grades yet still shows its
  Classroom-only due/missing/done counts (grade rollup fields just come
  back empty/null).

## 5. Teacher email links

Two related asks: resolve a teacher's real email from the staff
directory, and generate a pre-filled "email about this assignment" link.

- `StaffMember.full_name` / `.email` already exist per school
  (`backend/models.py`). Genesis's own `teacher` field is `"Last, First"`
  or `"Last1/Last2"` (co-taught sections, confirmed real: `"Borrelli/
  Squazzo"`); Classroom's "posted by" name is `"First Last"`. Neither
  matches `StaffMember.full_name` verbatim, so match on **last name only**
  (split on `/` or `,` for multi-teacher fields, normalize case, compare
  against `StaffMember.full_name`'s trailing word) — accept the ambiguity
  a common surname introduces; this is an assistive convenience link, not
  an authoritative directory lookup, and a wrong-teacher match is
  low-stakes (worst case: an email link to the wrong person with the same
  last name at that school, correctable by the parent before hitting
  send).
- `GET /students/{id}/bucket3/teacher-emails` → `{ [raw_teacher_or_poster_name]: email | null }`,
  built once per request from the child's own School's `StaffMember` rows
  — no new table, this is a computed lookup, not stored.
- Frontend: an "Email {teacher}" link wherever a teacher name is shown
  (schedule blocks, grade entries), `mailto:{email}?subject=...`. For a
  specific assignment, `subject` is autopopulated:
  `Question about: {assignment title} ({course name})`. No backend
  endpoint needed for this part — it's a client-side `mailto:` builder
  once the email is known.
- No match found → don't render a dead link; show nothing, same
  "don't show a broken affordance" rule as everywhere else in this app.

## 6. Classroom vs. Genesis breakdown

Already built (`GET /students/{id}/bucket3/audit`). No new backend work —
just needs to be reachable from both the parent's and the student's view
of the same student, which the new `get_current_student_or_guardian`
dependency (§0) makes automatic once every bucket3 route is switched over
to it.

## 7. AI-assisted suggestions — two tiers, deliberately different caching

**Tier A — per-assignment approach, shared across every student in the
same class.** The explicit ask: *"consistent across the same class for
all students."* This means keyed at the **course** level
(`course_code`+`course_section`, the same district-wide identifier
`ChildCourseGrade`/`ChildGradeEntry` already use to link Classroom and
Genesis), not per-student and not per-guardian — a second family with a
kid in the same section of the same class gets the same cached
suggestion, free.

```
AssignmentSuggestion
  id, course_code, course_section, normalized_title (bucket3_extract.py's
  normalize_title(), same function the audit match already uses),
  suggestion_text, model, generated_at
UNIQUE(course_code, course_section, normalized_title)
```

- `POST /students/{id}/bucket3/suggestions/assignment/{work_item_id}` —
  looks up by `(course_code, course_section, normalize_title(title))`;
  returns the cached row if one exists, otherwise calls the Anthropic API
  once, stores it, returns it. **On-demand only** — never generated
  automatically on import or on a schedule. This matters for cost control
  and because generating advice about work nobody's asked about yet is
  waste, not help.
- **Send the model only the assignment title and course name** — never
  the student's grade, never their due-date status, never anything from
  the description field verbatim if it could contain identifying details.
  This is a shared, cross-family cache; nothing personal may leak into a
  row another family's kid will also see.
- Only generate when the title is unambiguous enough to say something
  concrete (the model's own judgment, prompted for it) — a generic title
  like "Assignment 3" should decline rather than confabulate a specific
  approach. Store the decline too (so it's not re-attempted every time),
  distinguishable from a real suggestion.

**Tier B — "how should I tackle my list," personal, never cached.** This
is about one student's own specific mix of due/missing items at a given
moment — inherently not shareable, not deterministic input the way a
single assignment's title is.

- `POST /students/{id}/bucket3/suggestions/plan` — takes the student's
  current due+missing list (titles, course names, due dates only — same
  minimal-data-sent rule as Tier A), returns a short prioritized plan.
  Never stored, never reused for a different request even for the same
  student later — the input changes every time the list does, caching it
  would just as often show stale advice as good advice.
- Both tiers are explicitly user-triggered ("Suggest an approach" /
  "Suggest a plan" buttons) — never automatic, never on a schedule, same
  restraint as the rest of this app's Anthropic API usage.

## 8. Focused View

Both a parent and a student can have ADHD; the default view should not
require reading a dense dashboard to find "what do I do next."

- A view-mode toggle, persisted in `localStorage` (same pattern as the
  existing theme toggle — no backend, no account setting).
- **Focused mode** shows exactly three things:
  1. The "Right now" card (§1).
  2. **One** next action — deterministically chosen: the not-Done item
     with the earliest `due_date` among Missing items first, then Due
     items (a missing item always outranks an upcoming one) — never a
     personalized/AI-ranked pick, the ordering rule must be predictable
     and re-derivable by the person looking at it.
  3. One progress bar: `done / (done + missing + due)` for the *current
     marking period* (reuses the `/audit`'s current-MP resolution) —
     "how close am I to caught up."
  A single "Show more" expands into the full view below it (Full detail
  never removed, just not the default) — collapsing loses no data, only
  changes what's shown first.
- **Full detail mode** is everything: schedule, due/missing/done tables,
  announcements, grades, audit, per-course progress, suggestion buttons.
- Visual guidelines for whichever mode is showing the fuller UI (apply
  throughout, not just Focused mode): one accent color reserved for
  "needs attention" (Missing items, low grades) and used nowhere else;
  no auto-refreshing or auto-playing content; short microcopy over
  paragraphs; one primary button per screen section; generous whitespace
  over dense tables as the *default* rendering (a table is still fine
  behind an explicit "show as table" toggle, e.g. for the full grade
  list) — same spirit as this app's existing design-system rules in
  `frontend/src/ui.css`, just named explicitly here so it isn't lost
  restyling this specific set of pages.

## Data model summary (new)

```
students.user_id                      nullable, unique FK -> users.id

student_account_invites               mirrors guardian_invites, different relationship
child_work_item_progress              student_id, work_item_id, done, marked_by_user_id
child_work_items.posted_raw           new column
child_work_items.posted_date          new column
                                       (.status column already exists, just needs a populator)

assignment_suggestions                shared/global, keyed by (course_code, course_section, normalized_title)
```

## API summary (new)

```
POST   /students/{id}/account-invites
GET    /student-account-invites/{token}
POST   /student-account-invites/{token}/accept

GET    /students/{id}/bucket3/right-now
GET    /students/{id}/bucket3/announcements
GET    /students/{id}/bucket3/progress
GET    /students/{id}/bucket3/teacher-emails
POST   /students/{id}/bucket3/workitems/{work_item_id}/complete
POST   /students/{id}/bucket3/suggestions/assignment/{work_item_id}
POST   /students/{id}/bucket3/suggestions/plan
```

Every existing and new `/students/{id}/bucket3/*` route switches its
access check from guardian-only (`_get_own_student`) to
`get_current_student_or_guardian` (§0) — one place to change, every route
benefits.

## Explicitly out of scope for this pass

- Elementary/preschool coursework views (no verified data shape yet).
- Any automatic/scheduled AI generation — both suggestion tiers are
  strictly user-triggered.
- Enforcing or calculating district-specific makeup-grade math.
- Real-time notifications/push of any kind.
- A parent "logging in as" a student — student accounts are real,
  separate logins, invite-only.

## Build order

1. **Student accounts** — invite flow, `Student.user_id`,
   `get_current_student_or_guardian`. Unlocks "the child logs in and sees
   the same data," which several later phases assume exists.
2. **Right now card** — pure read, reuses `bell_schedule.py`'s existing
   algorithm against already-captured data. No new extraction.
3. **Work-item completion tracking** — the core of the actionable to-do
   list (`ChildWorkItemProgress` + the toggle endpoint + Due/Missing/Done
   derivation).
4. **Status + posted-date extraction** for Classroom (verify against a
   real capture before writing the regex) — unlocks a real "Missing"
   signal from Classroom itself and the Announcements feed.
5. **Per-course progress rollup** + the low-grade/makeup flag.
6. **Teacher-email resolution** + `mailto:` links, including the
   per-assignment "email about this" variant.
7. **Assignment suggestions** (Tier A, shared/cached) and **plan
   suggestions** (Tier B, personal/uncached).
8. **Focused View** toggle — applied last since it's a display wrapper
   over everything built in 1–7, not new data.
