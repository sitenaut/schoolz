# High school class pages — design notes

Source of the analysis: Cherry Hill East's Activities site,
`https://sites.google.com/chclc.org/cheactivities/home` (19 pages, crawled
2026-09-22), plus everything it links to.

## 1. What's actually there

The site is maintained by the Activities office (Holly Sassinsky,
coordinator; Debbie Barr, secretary) and is the only place a lot of this
information exists. Inventory, with the shape of each source:

| Source | Shape | Auth | Notes |
|---|---|---|---|
| The Sites pages themselves | Server-rendered HTML | none | `curl` gets the full text; no Playwright needed |
| Activities calendar | Public Google Calendar | none | ICS feed works (see below), 37 live VEVENTs |
| Morning Announcements | One Google Doc, appended daily | none | `/export?format=txt` works; the richest source on the site |
| Letters / FAQs / bell schedule / bus map | Drive PDFs, linked as `/file/d/<id>/preview` | none | `uc?export=download&id=<id>` works; most have a real text layer |
| Clubs & Advisors | Drive spreadsheet | none | `/export?format=csv` |
| Sign-ups | Google Forms + SignUpGenius | none | Deadlines attached (e.g. t-shirt size by 8/6) |
| Payments | PaySchools (external) | yes | Only the *schedule* is public; balances are not |

Confirmed working, unauthenticated:

```
https://calendar.google.com/calendar/ical/c_4837783764d5da36f7732c71b14c0cd54c30c92ebd264031a765ed718a16edf4%40group.calendar.google.com/public/basic.ics
https://docs.google.com/document/d/11cONmfYKtj6LFyuYGnRQjVv1Y9z8w2-wF9O55onBWoA/export?format=txt
https://drive.google.com/uc?export=download&id=<file id>
```

## 2. The organizing insight

**For a high school, the unit of relevance is the graduating class, not the
school.** Nearly everything on this site is keyed by class year, and the
site's own information architecture says so: the top-level nav is Class of
2027 / 2028 / 2029 / 2030.

Concrete examples from the live site:

- Senior trip: *"Pay $775.00 by November 20th, 2026"* — the single most
  important date of the year for the Class of 2027, and pure noise for the
  other three classes.
- *"Wednesday, September 16th (Day 3), DiBart Gym"* is picture day for
  sophomores and juniors; freshmen already took theirs at orientation on
  August 26th; **seniors do not take pictures that day at all** and instead
  have eight separate CADY portrait dates in the Library Annex.
- Parking permits: seniors first, juniors only if spots remain.
- *"This visit is open for 10th through 12th graders"* (Temple Rome rep).
- Class officer elections are a freshman-only story in September.

The district calendar can't carry any of this without drowning. That's the
user's instinct and it's right: **same data, wrong altitude.** A class page
is the correct altitude.

Also note the *phase* vocabulary the school uses: "Spring of freshman year",
"Fall of junior year". The senior trip payment ladder spans four years and
is described relative to the cohort, never to a calendar. Keying on
graduating year — not grade number — is what makes that stable. A grade
number silently means a different set of kids every July; "Class of 2027"
never does.

## 3. Data model

### 3.1 `SchoolContentItem.applies_to_grad_years: list[int] | None`

The smallest change that unlocks everything else, and an exact mirror of the
existing `applies_to_school_types` — same nullable-means-everyone semantics,
same "a filter on top of the row, not N duplicated rows" rationale.

- `null` → applies to the whole school (the default; nothing regresses).
- `[2027]` → seniors only.
- `[2028, 2029]` → real case: the Sept 16 picture day.
- `[2027, 2028, 2029]` → real case: "open to 10th through 12th graders".

A list, not a scalar, because the multi-class cases above are genuinely
common and collapsing them to "all" throws away the only thing that makes
the item worth showing.

### 3.2 `SchoolClassYear`

The page entity. One row per `(school_id, grad_year)`.

```
school_id, grad_year
label                 # "Seniors" / "Juniors" / … — derived, but overridable
grade_level_principal_staff_id
advisor_staff_ids     # JSON list; East has two per class
instagram_url         # every class has its own, e.g. ch.east2027
source_page_url       # the Google Sites page this was built from
```

Advisors resolve against the existing `StaffMember` directory, exactly like
`SchoolContentItem.staff_member_id` — ambiguous match resolves to none,
never a guess.

Route: `/schools/{slug}/class-of-{year}`. Public like every other read.

### 3.3 `Student.grad_year: int | None`

Needed to default a signed-in guardian to the right class. Typed on My
Children, or derived from a Genesis grade level using the same Jul–Jun
school-year boundary the rest of the app already uses. Null is fine — the
page still works, the class picker just has no default.

### 3.4 `ClassPayment` (sidecar)

The senior trip page is a **payment ladder**, and a `category="deadline"`
row with a title cannot answer "how much do I still owe". Precedent for a
sidecar: `LunchMenuItem` alongside `category="lunch_menu"`.

```
school_class_year_id
sequence, kind        # 1..N; "optional" | "official"
label                 # "Optional Deposit #3"
amount_cents          # NULL = "not announced yet", never zero
window_opens_at, window_closes_at
methods               # JSON: ["payschools_ach", "payschools_card", "cash", "check"]
payschools_item_name  # "EAST - Senior Trip 2027 - Optional Deposit #4"
refundable_until
notes
```

`amount_cents` null is load-bearing and follows the same rule as
`late_credit()` returning None and `ChildWorkItem.points_possible` being
null: **"unknown" must stay distinguishable from "known to be zero."** The
Class of 2028 and 2029 ladders are currently *entirely* TBD ("Amount TBD in
Spring of 2027") and showing $0 there would be a lie.

## 4. The class page template

Ordered by the house rule — **actions first, reference last** — and with no
photos, per the product call.

```
┌ Class of 2027 · Seniors · Cherry Hill East      [27][28][29][30] ┐
│                                                                   │
│  ▸ NEXT FOR THIS CLASS                                            │
│    Senior trip — 3rd deposit, $775 due Fri Nov 20                 │
│    [Pay on PaySchools]   (ACH $1.95 · card 4%)                    │
│                                                                   │
│  ▸ MONEY & DEADLINES              total $2,275 · $1,500 posted    │
│    ✓ Optional #1  $300   closed Apr 2024                          │
│    ✓ Optional #2  $300   closed Nov 2024                          │
│    ✓ Optional #3  $300   closed Jun 2025                          │
│    ✓ Optional #4  $350   closed Dec 2025                          │
│    ✓ Official #1  $750   due May 29 2026                          │
│    ● Official #2  $750   due Sep 25 2026      ← sign-up deadline  │
│    ○ Official #3  $775   due Nov 20 2026                          │
│    Insurance: basic any time before final payment · CFAR Oct 2–15 │
│                                                                   │
│  ▸ DATES FOR THIS CLASS                                           │
│    Sep 29  Senior portraits — Library Annex, 9:30a–3:30p          │
│    Oct 8   Senior portraits                                       │
│    Mar 12–17 2027  Senior trip                                    │
│                                                                   │
│  ▸ OPEN NOW — FORMS & SIGN-UPS                                    │
│    Yearbook photo choice (Basic session)     [Form]               │
│    ~~Free t-shirt size — closed Aug 6~~                           │
│                                                                   │
│  ▸ WHO TO ASK                                                     │
│    Grade-level principal · Mrs. Kate Pereira, Ms. Genene Barnes   │
│    Class advisors · Dr. Kathy Lewis, Mrs. Jaclyn Walker           │
│    Trip questions · hsassinsky@chclc.org                          │
│    Payments · dbarr@chclc.org (A015, across from the nurse)       │
│                                                                   │
│  ▾ FAQ                                                            │
│  ▾ Letters & documents                                            │
│  ▾ Class Instagram                                                │
└───────────────────────────────────────────────────────────────────┘
```

Notes on specific choices:

- **Closed items are struck through, not hidden.** "Did I already miss it"
  is the actual question a parent has; an item that silently vanishes
  answers it wrong. Same reasoning as Focus dropping past-cutoff work only
  because Details still has it.
- **One "next" card.** The dashboard's limited slots go to the thing where
  acting now still protects something — directly the Focus-view rationale.
- **The payment ladder replaces ~200 lines of prose.** The live 2027 page
  enumerates seven scenarios ("IF YOU MADE 2 OPTIONAL PAYMENTS of $300.00…")
  because it can't know what you paid. We don't have to reproduce that:
  store the canonical ladder, and let the person tick off what they've paid
  (per-account, like `CourseDisplayPreference` — keyed on `user_id`, never
  `student_id`, since one guardian's payment tracking must not leak to
  another guardian of the same kid). `owed = total − ticked`. One sentence
  instead of seven branches.
- **Class switcher always visible.** A guardian with a junior and a freshman
  needs both, and a curious sophomore's parent should be able to look ahead
  at what senior year costs — which is, per the school's own letters, the
  entire point of the four-year optional deposit schedule.

## 5. `/schools` changes for high schools

Currently one page shape for every school. Three type-conditional changes:

1. **Class strip** directly under the sticky actions when
   `school_type == "high"`: four chips linking to the class pages, the
   signed-in guardian's own class first.
2. **The sticky action row should be type-aware.** Elementary's row (absence
   / nurse / counselor / SACC / office) is wrong for a high school, where
   the confirmed real needs are absence, counselor, **parking permit**,
   athletics, and the activities office. SACC is meaningless here.
3. **Today card, HS variant.** The day rotation is already parsed
   (`hs_rotation.scan`, and the announcements doc independently states "Day
   6" every morning — a free cross-check). Add one line: what's happening
   at LB1/LB2 today, filtered to this kid's class.

`/schools` list view: high schools get the class chips inline, so a parent
can go straight to Class of 2029 without a stop at the school page.

## 6. Parsing plan

Ranked by value-per-unit-of-work. Tiers 0 and 1 are most of the payoff.

### Tier 0 — the activities ICS feed (no LLM, do first)

The Google Calendar embedded on the home page has a public ICS feed. This is
the *same shape* as `District.ics_feeds`, so `services/district_calendar.py`
ports over almost unchanged: `external_uid` for re-scan idempotency,
bidirectional cross-source claiming so a newsletter-sourced row isn't
doubled.

- New: `School.ics_feeds`, job kind `school_calendar.scan`.
- Fields present and useful: `SUMMARY`, `DTSTART`, `LOCATION` (literally
  `ROOM B233`), `DESCRIPTION` (some HTML, needs stripping).
- **Tag these `source="school_ics"` and default them OFF in the general
  calendar.** Thirty club interest meetings is exactly the "too much detail
  for the general calendar" problem. Precedent exists: "Show day rotation"
  and "Exclude district" are both shared filters in `lib/mySchools.tsx`.

### Tier 1 — the Morning Announcements doc (the richest source)

One doc, appended newest-first, one block per school day:

```
Tuesday, September 22, 2026
Day 6
* The Ethics Bowl Club will meet TODAY during both LBs in the Cougar Conference Room…
* ALL FRESHMEN should report to the Cafeterias at 7:30am TOMORROW for class officer speeches…
```

Split deterministically on the date header, then one structured tool-use
call per day block (temperature=0, `items` first in the schema — the
existing `content_extractor.py` rules all apply). Extract per bullet:
`kind` (club meeting / game / result / deadline / logistics / class),
`audience` (grad years, or all), `when`, `lunch_block` (LB1 / LB2 / both /
after school / before school), `room`.

Three traps worth writing down before they cost a day each:

1. **"TODAY" means the block's own date, not the scan date.** Resolve every
   relative reference against the date header. This is the same class of bug
   as `resolve_due_date` recomputing a year that was printed right there —
   an explicit anchor exists, so use it.
2. **The same event appears on three or four consecutive days** (TODAY /
   TOMORROW / "next Tuesday"). Dedup on `(resolved_date, club, room)` and
   keep the *most recently published* mention, because that's the one
   carrying corrections: *"Unfortunately, The Miracle League meeting for
   today has been rescheduled for Wednesday, Sept 23."* This is supersede
   semantics, already built.
3. **`Day N` in the header cross-checks `hs_rotation`.** Free validation of
   a PDF-derived table that's explicitly marked "tentative". A disagreement
   is a real signal, not noise.

Payoff: club meetings at lunch are the thing a high schooler most reliably
misses, and nothing else in the district publishes them. Announcements are
also the only source for same-day cancellations — *"There will be NO LATE
BUSES TODAY"* — which is `school_status`-shaped.

Cadence: 2h on school days, not 12h. The content is the day's content.

### Tier 2 — the Google Sites pages

- **No scraper needed.** Google Sites server-renders; plain `httpx` +
  BeautifulSoup gets everything. That keeps ~20 renders off the 1GB
  Chromium that already absorbs the 12h burst.
- **Never regex numbers or dates out of the raw DOM.** Sites splits text
  mid-token across spans: `$750.00` arrives as `$7` + `5` + `0.00`, and
  `Class of 2027` as `Class of 202` + `7`. A naive money regex reads `$7`.
  Join inline text within a block *first*, then hand normalized text to the
  model. (Every number in this document was recovered that way.)
- **The URL answers the hardest question for free.** A path matching
  `class-of-(\d{4})` sets `applies_to_grad_years=[year]` on everything
  extracted from that page, deterministically, before the model sees a word.
  Attribution is the part LLM extraction is worst at, and here it's a regex.
  The sub-page slug gives the topic: `senior-parking`, `senior-portraits`,
  `senior-trip-2027`, `9th-grade-picture-day`, `freshman-orientation`.
- **Site map is free too**: every page renders the full nav, so crawling
  home yields all 19 paths with no sitemap or API.
- Hash the normalized per-page text and skip extraction when unchanged —
  same trick as `SmoreBlock`'s content hash.

### Tier 3 — the payment ladder

Its own extraction pass, because the prose is genuinely hostile. Extract
**only the canonical ladder** — the numbered deposits with amounts, windows
and methods, plus the total — and ignore the seven per-scenario branches
entirely. They're derivable.

Real facts to capture that a generic "deadline" row would lose: ACH is
$1.95 and card is 4% and the school will not reimburse it; cash/check are
accepted for official deposits but never for optional ones; **cash/check
cannot be accepted June 1–18 because of graduation prep**; deposits are
fully refundable until September of senior year; CFAR insurance is
purchasable *only* October 2–15, no exceptions.

### Tier 4 — linked PDFs, Docs and Sheets

- Drive `/file/d/<id>/preview` → `uc?export=download&id=<id>`, confirmed
  unauthenticated. Most have a real text layer (pdfplumber); keep the
  existing "pass the PDF to Claude as a native `document` block" path for
  the graphical month calendars.
- Docs → `/export?format=txt`. Sheets → `/export?format=csv`: the
  "2026-27 Clubs and Advisors" sheet is a ready-made club directory with
  advisor names that merge into `StaffMember` the same way `classify_role`
  feeds the contact grid.
- **Dedup by Drive file id, not URL.** The CADY picture-day FAQ
  (`1LrYDJcyshnkh0lEYVRo_uEANwImix68f`) is linked from three different class
  pages. One parse, three attributions.
- **Filter vendor marketing.** The CADY senior-portrait FAQ is two pages of
  "What Makes Senior Portraits Different?" with no school-specific content
  at all. Heuristic: a PDF whose text names neither the school nor a date
  isn't school content.

### Tier 5 — deliberately not parsed

Officer photos, Senior Hall of Fame, Past Disney Trips, historical SGA
officer pages, anything before the current academic year. Archive, not
information.

## 7. How this lands elsewhere in the app

- **General calendar**: class items show for a signed-in guardian's own
  kid's class, and for an anonymous visitor show labeled `[Class of 2027]`
  rather than being hidden — the same degrade-don't-demand-login posture as
  `GET /calendar`, and the same per-row labeling as
  `districtItems.ts:expandItemRows`.
- **Focus / kids view**: a class deadline with money attached is precisely
  the "acting now still protects something" shape Focus is built around.

## 8. Open questions

- Does the Genesis capture carry a grade level we can derive `grad_year`
  from, or does it have to be typed once on My Children?
- The Activities site is one school's. Cherry Hill West presumably has an
  equivalent; the parsers should be built per-source-shape (Google Sites,
  Google Doc announcements, public ICS), not per-school, so West drops in.
- Nothing here has a change feed. Per-page content hashing handles it, but
  the announcements doc grows unboundedly — parse only blocks newer than
  the last-seen date header.
