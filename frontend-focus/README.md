# frontend-focus — student "Focus" view (prototype)

A second front-end for the kids/student view, served from the **same origin**
as `schoolz-web` at `/focus/`. Same backend, same session, separate app.

## Why same origin, not a subdomain

Both auth modes keep the session in `localStorage`, which is scoped to the
**origin**, not the path:

- local mode — `schoolz_token`, written by `frontend/src/api.ts`
- supabase mode (prod) — `sb-<project-ref>-auth-token`, written by supabase-js

Serving this app from a path on the same host means a login in `schoolz-web`
is already signed in here, with no token passing, no CORS change, no backend
change, and no new OAuth redirect URIs. A subdomain would share none of it and
would need either cookie auth on the parent domain or a token hand-off through
the URL fragment — the latter being exactly the shape `scrubUrl()` exists to
strip out of RUM.

## Build and serve

```
cd frontend-focus && npm install && npm run build      # -> dist/, base=/focus/
```

`vite.config.ts` sets `base: "/focus/"`. Without it every asset URL points at
the main app's root and 404s.

nginx serves it from a `location /focus/` block added in
`frontend/nginx.conf.template`, placed **before** `location /` so the crawler
/prerender branch never intercepts it (everything here is behind auth, so
there is nothing to index).

To try it against the running local stack, copy the build into the nginx
container — the same trick CLAUDE.md documents for verifying UI with no
browser on the host:

```
docker cp dist/. schoolz-web-local:/usr/share/nginx/html/focus/
# then open http://localhost:3000/focus/
```

Because that is the same origin as the main local app, signing in at
`http://localhost:3000/` signs you in here too.

## Design constraints (ADHD-informed) — these are rules, not styling

The mockup this was built from came out of a specific set of principles, and
the code enforces them rather than merely resembling them. Change them
knowingly.

1. **Rule of 3 to 5.** `FocusTab` hard-caps Up next at 4 cards and Needs
   attention at 3 rows (`UP_NEXT_CAP`, `ATTENTION_CAP`). Overflow sits behind
   `Capped`, a "Show N more" barrier that reveals one more cap's worth per
   press — the boundary is redrawn, never removed. Nothing on the dashboard
   scrolls indefinitely.
2. **Outsourced prioritisation.** Needs attention renders above everything
   else and is the only red thing on the screen. The app decides what's
   most important; she doesn't have to.
3. **Time blindness.** The dashboard is a bouncer: only *missing*, *due
   today*, or *due the next school day* get in. "Tomorrow" on a Friday is
   Monday (`courses.ts:horizon`), labelled as such. Everything further out
   exists only in Subjects → tap a tile → `CourseSheet`. That separation is
   what gives permission to ignore next week tonight.
4. **Progressive disclosure.** A card is Subject + Title + Checkbox. The due
   date is the *group heading*, not a per-card label. Teacher, link, points,
   Classroom's status: all wait in the sheet until tapped.
5. **Dopamine checkpoints.** The progress bar is scoped to *today's set*
   (missing + horizon), not the marking period — at "10 of 31" finishing
   tonight's four things moved it 13%; scoped, it goes to 100%. Clearing the
   dashboard shows `InboxZero`. Finished items collapse behind a toggle so
   the reward isn't a list of struck-through cards.

A per-device `localStorage` set (`focus_cleared_<date>`) records ids checked
off through this screen today, so clearing a two-week-old missing item still
credits the bar. It's a convenience, not a record.

## What it renders

Three screens from the mockup, bound to endpoints that already exist:

| Screen | Endpoint |
| --- | --- |
| Daily progress, Needs attention, Up next | `GET /students/{id}/bucket3/todo` |
| Subject tiles + badge counts | `GET /students/{id}/bucket3/progress` |
| Period letter on a tile | `GET /students/{id}/bucket3/schedule` |
| Mark as done | `POST /students/{id}/bucket3/workitems/{item_id}/complete` |

## Prototype caveats — read before extending

1. **`src/api.ts` duplicates the auth layer.** It reads supabase-js's own
   storage key rather than depending on supabase-js, to avoid copying
   `AuthContext`'s deadlock fix into a second place where it can regress
   independently. That trade is fine for a prototype and wrong for
   production: the real version should import a shared workspace package so
   `apiFetch`/`AuthContext` exist once. This is the single most important
   thing to change before this ships.
2. **No RUM/Faro**, no `react-router` (tabs are local state), no prerender.
3. **Tiles come from `/bucket3/progress`, not the schedule**, because the
   badge count is the point. The period letter is attached only on an exact
   course-name match, which usually fails: Genesis says `GEOMETRY A`, Classroom
   says `GEOM A Per A 2026-27 210-1`, and the link between them is the
   district code embedded in the Classroom name, which schedule rows don't
   carry. Closing that gap deterministically is a real piece of work — see the
   `course_key` note in CLAUDE.md. Guessing across it would mean fuzzy name
   matching, which this codebase deliberately avoids.
4. **"Clubs" has no model.** The club-shaped things in the data
   (`Class of 2029`, `Beck Bridge Tutoring`, `Advanced Percussion`) are
   Classroom courses with no district code, which is the same gap as (3).
5. **Course names are shortened for display only** (`src/courses.ts`).
   Nothing keys off the shortened string.
