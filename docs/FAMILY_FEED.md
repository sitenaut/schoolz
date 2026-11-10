# Family feed (experimental)

An app the family uses reads that family's school data from schoolz: the
children, their schools, school days, each child's schedule, school events
and newsletter items, schoolwork and grades. The first and only app is
billz, the owner's household app. The data stays the same data the site
shows the family; this is a second way to read it, not a copy.

Experimental: **only a super admin can approve a connection, and the feed
answers only while the approving person is still one.** Opening it to other
families needs the privacy page to say so first.

Code: `backend/routers/family_connections.py` (connect),
`backend/routers/family_feed.py` (feed), `auth.FAMILY_KEY_ROUTES` (what the
key reaches). Admin → Connected apps lists and disconnects them.

## Connect

The same device flow as `scripts/schoolz-api.sh login`: the app starts a
request and polls; the person approves it in a browser where they're signed
in. The key is minted when the app collects it, so it never passes through
a person, a chat or the database.

1. `POST /family-connections/start` with `{"client_name": "billz"}`:

   ```json
   {"device_code": "<secret, keep it>", "user_code": "BCDF-GHJK",
    "approve_path": "/admin/connected-apps/approve", "expires_in": 600, "interval": 3}
   ```

   Only a known app's name is accepted (`KNOWN_APPS`); anything else is
   `400 {"detail": "Unknown app"}`. Too many open requests from one
   connection is `429`.
2. Show the person the code and the link
   `https://schoolz.sitenaut.com/admin/connected-apps/approve?code=BCDF-GHJK`.
   They check the code matches and press Connect.
3. Poll `POST /family-connections/token` with `{"device_code": "..."}` every
   `interval` seconds:

   ```json
   {"status": "pending", "key": null, "connection_id": null}
   ```

   `status` is `pending`, `denied`, `expired` or `approved`. `approved`
   carries `key` (`szf_...`) and `connection_id`, once: the same device code
   reads `expired` after that. A request expires 10 minutes after it starts,
   or 5 minutes after approval if the key isn't collected. Start again on
   `denied` or `expired`.
4. Send the key as `Authorization: Bearer szf_...`.

The key reaches two routes and nothing else:

| Route | Answer |
|---|---|
| `GET /family/feed` | the feed, below |
| `POST /family-connections/self/revoke` | `204`; the app's own Disconnect |

On any other route it is `403 {"detail": "A family connection key can only read the family feed"}`.
A key that was disconnected (Admin → Connected apps, or its own revoke) is
`401 {"detail": "This app isn't connected to schoolz any more"}`: stop and
connect again. If the approving person is no longer a super admin the feed
is `403 {"detail": "The family feed is experimental: super admins only for now"}`.

## Feed

`GET /family/feed?start=YYYY-MM-DD&end=YYYY-MM-DD`: local (Eastern) dates,
inclusive. Defaults: a week back to 60 days ahead. `end` must be on or after
`start` and at most 120 days later, else `422`.

A super admin's own browser session reads it too, for a look.

```json
{
  "version": 1,
  "generated_at": "2026-11-09T18:30:00Z",
  "start": "2026-11-02",
  "end": "2027-01-08",
  "children": [
    {"id": "c-1", "first_name": "Alex", "school_id": "s-1", "grad_year": null,
     "specials": [{"rotation_day": 3, "subject": "Art", "teacher": null}],
     "classroom_seen_at": null, "genesis_seen_at": null, "needs_login": false}
  ],
  "schools": [
    {"id": "s-1", "slug": "example-elementary", "name": "Example Elementary School",
     "short_name": "Example", "school_type": "elementary", "district_name": "Example Public Schools",
     "start_time": "8:50", "end_time": "3:20", "early_dismissal_time": "1:05", "delayed_opening_time": null}
  ],
  "items": [
    {"uid": "day:s-1:2026-11-10", "kind": "day", "school_id": "s-1", "child_id": null,
     "date": "2026-11-10", "end_date": null, "start_at": null, "end_at": null, "all_day": true,
     "title": "School day", "detail": "8:50–3:20", "status": "open", "category": null,
     "source": null, "link_url": null,
     "data": {"label": null, "rotation_day": "Day 3", "blocks": null}, "hash": "1f0c9a2b7d3e4f50"},
    {"uid": "schedule:c-1:2026-11-10", "kind": "schedule", "school_id": "s-1", "child_id": "c-1",
     "date": "2026-11-10", "title": "Day 3", "detail": "Art", "status": "open",
     "data": {"rotation_day": "Day 3", "timed": false, "long_blocks": false,
              "blocks": [{"name": "Special", "start_label": null, "end_label": null,
                          "course_name": "Art", "teacher": null, "room": null}]}, "hash": "..."},
    {"uid": "item:e-1", "kind": "event", "school_id": "s-1", "date": "2026-11-13", "all_day": true,
     "title": "Picture Day", "detail": "Order forms went home Monday.", "category": "event",
     "source": "newsletter", "link_url": null,
     "data": {"school_ids": ["s-1"], "scope": "school", "applies_to_grad_years": null,
              "newsletter_url": "https://app.smore.com/n/abc12", "extracted_at": "2026-11-09T13:05:00Z"},
     "hash": "..."},
    {"uid": "item:e-2", "kind": "news", "school_id": "s-1", "date": null,
     "title": "Book fair volunteers needed", "category": "volunteer", "source": "newsletter",
     "data": {"school_ids": ["s-1"], "scope": "school", "applies_to_grad_years": null,
              "newsletter_url": "https://app.smore.com/n/abc12", "extracted_at": "2026-11-09T13:05:00Z"},
     "hash": "..."},
    {"uid": "assignment:w-1", "kind": "assignment", "school_id": "s-2", "child_id": "c-2",
     "date": "2026-11-12", "title": "Lab report", "status": "due", "category": "assignment",
     "source": "classroom", "link_url": "https://classroom.google.com/c/.../a/.../details",
     "data": {"course_name": "Science 7", "due_raw": "Due Nov 12", "done": false, "done_source": null,
              "classroom_status": null, "points_possible": 20.0, "grade": null, "teacher_name": "Ms. Example"},
     "hash": "..."},
    {"uid": "course_grade:c-2:SCI7-02:MP2", "kind": "course_grade", "school_id": "s-2", "child_id": "c-2",
     "title": "Science 7", "source": "genesis",
     "data": {"course_code": "SCI7", "course_section": "02", "marking_period": "MP2",
              "grade_percent": 91.5, "last_grade_posted": "11/06/2026"}, "hash": "..."},
    {"uid": "grade:c-2:g-1", "kind": "grade", "school_id": "s-2", "child_id": "c-2",
     "title": "Quiz 3", "status": null, "category": "Quizzes", "source": "genesis",
     "data": {"course_name": "Science 7", "course_code": "SCI7", "course_section": "02",
              "marking_period": "MP2", "weekday_date": "Thu 11/06", "score_earned": 18.0,
              "score_possible": 20.0, "percent": 90.0, "first_seen_at": "2026-11-07T01:10:00Z"},
     "hash": "..."}
  ]
}
```

Every item has every top-level field (shortened above). Only `uid`, `kind`,
`title`, `all_day`, `data` and `hash` are never null.

| kind | uid | one per | in a snapshot when | `status` | `data` |
|---|---|---|---|---|---|
| `day` | `day:{school_id}:{date}` | school, weekday | its date is in the window | `open`, `closed`, `early_dismissal`, `delayed` | `label` (a closure's reason), `rotation_day` (`"Day 3"`, `"Day C"` or null), `blocks` (a high school's letters that day) |
| `schedule` | `schedule:{child_id}:{date}` | child, school day | the next 15 school days from today (up to 21 days), for a child whose school publishes rotation days and who has specials or a Genesis class list | as `day` | `rotation_day`, `timed`, `long_blocks`, `blocks` (`name`, `start_label`, `end_label`, `course_name`, `teacher`, `room`) |
| `event` | `item:{id}` | dated school or district item | its date is in the window | null | `school_ids`, `scope` (`school` or `district`), `applies_to_grad_years`, `newsletter_url`, `extracted_at` |
| `news` | `item:{id}` | undated newsletter item | `extracted_at` is on or after `start` | null | as `event` |
| `assignment` | `assignment:{id}` | Classroom work in the current marking period (Gradez's to-do) | always | `missing`, `due`, `done`, `no_due_date` | `course_name`, `due_raw`, `done`, `done_source`, `classroom_status`, `points_possible`, `grade`, `teacher_name` |
| `course_grade` | `course_grade:{child_id}:{code}-{section}:{marking_period}` | class, current marking period | always | null | `course_code`, `course_section`, `marking_period`, `grade_percent`, `last_grade_posted` |
| `grade` | `grade:{child_id}:{external_uid}` | Genesis graded entry | schoolz first saw it on or after `start` | `Missing`, `Late`, `Exempt` or null | `course_name`, `course_code`, `course_section`, `marking_period`, `weekday_date` (as Genesis prints it), `score_earned`, `score_possible`, `percent`, `first_seen_at` |

- `title`, `detail`: a `day`'s title says the status ("No school: Thanksgiving
  Recess") and `detail` its hours; a `schedule`'s title is the rotation day
  and `detail` the classes or special; an event's `detail` is its description.
- `category` on events and news is schoolz's (`event`, `deadline`,
  `initiative`, `reminder`, `marking_period`, `policy_change`, `procedure`,
  `program`, `busing`, `funding`, `volunteer`, `org_club`, `pta`); on
  assignments it is Classroom's item type. `source` says where schoolz read
  it: `newsletter` (a Smore or Mailchimp issue, a flyer), `ics_feed`,
  `district_pdf`, `school_events_doc`, `marking_period`, and so on.
- A district item reaching more than one child's school appears once, with
  `school_id` null and every school in `data.school_ids`.
- Left out: athletics, high-school class-page activity, staff introductions,
  lunch menus, merchandise ads. Assignments come only once Backpack Capture
  has brought Classroom data for the child (`classroom_seen_at`), grades
  Genesis data (`genesis_seen_at`). `needs_login` is true when a child's
  Google sign-in ran out and Backpack Capture is waiting for it.

## Sync

Upsert by `uid`; `hash` changes when anything in the item does. Delete an
item when a snapshot whose window still covers it no longer has it: it was
withdrawn, corrected or deleted at its source (a newsletter correction is a
new `uid` with the old one gone; a revised district calendar PDF replaces
every row). "Covers" is per kind, as in the table: the date for `day` and
`event`, `extracted_at` for `news`, `first_seen_at` for `grade`, today on for
`schedule`, always for `assignment` and `course_grade`. An item outside the
window has just aged out.

There is no "changed since" parameter on purpose: most of what feeds this
has no updated_at to ask about.

## What never leaves schoolz

A child's last name and district student ID (with the first name, the
auto-match key that would let the holder link their own account to the
child), the child's login and invite emails, who marked work done, help
requests, teacher emails, captured pages, other families' children, and
anything another guardian of the same child keeps for themselves.

## Cost

Hourly is plenty, and please no more often than every 15 minutes. A read
calls no model, no scraper and no weather service, and is English only.
The data changes when scans run (district calendars every 12 hours, Smore
on Mondays and whenever email brings an issue) and when a parent's Backpack
Capture sends pages (by hand, or every 4 hours if they turned that on).

## Testing

There is no staging environment. The local stack (`AUTH_MODE=local`) serves
the same routes, and `backend/tests/test_family_feed.py` covers the flow,
the key's reach and the feed's contents.
