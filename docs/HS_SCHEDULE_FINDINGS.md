# High school schedules: one timetable, five vocabularies

Finding from comparing two schedule printouts for one real Cherry Hill East 10th grader (2026-27) against the district's rotation calendar, the school's bell-schedule PDF, and the Genesis screens backpack-capture already imports. The student's name, ID, bus stops, and rooms are deliberately left out. A child's full timetable says where they are every hour of the day.

## The two documents are the same system

Both PDFs come from **Genesis**. They're the two buttons under "Print Schedule" on the student summary page (`genesis_daily_view.txt` fixture: *"Print schedule in list format" → List*, *"Print schedule in bell format" → Bell*):

| | **List print** (`genesisschedule.pdf`) | **Bell print** (`blockschedule.pdf`) |
|---|---|---|
| Shape | One row per course section | A grid: 6 columns × 7–8 rows, one page per quarter |
| Has | Term (FY/S1/S2), rotation-day eligibility, bus routes | Clock times per rotation day, which blocks meet on which day |
| Lacks | Clock times, which days a block is *dropped* | Term codes (only as a suffix glued to the room), bus |
| Dated? | Yes (`09/20/2026`) | No. An undated printout goes stale silently after a schedule change |
| Pages | 1 | 6 pages for 2 distinct schedules (Q1 = Q2, Q3 = Q4; Days 1–4's last block spills onto its own page) |

Neither one is complete, and they disagree in their vocabulary even though Genesis produced both.

## How the East/West schedule actually works

Worked out from the Bell grid and confirmed against the legend on the district's *2026-2027 Day Schedule* PDF (`tests/fixtures/hs_day_rotation_2026_27.pdf`). They agree exactly:

- **Eight course blocks, A–H**, plus two half-blocks in the middle of the day, **L1 and L2**.
- **A 6-day rotation, Day 1–Day 6**, that runs independently of the weekday. Holidays don't consume a rotation day, so Day 1 falls on any weekday.
- **Days 1–4 are "drop" days**: six 57-minute blocks. The morning drops one of A–D and the afternoon drops one of E–H, in a fixed order (Day 1 = A,B,C,E,F,G; Day 2 = D,A,B,H,E,F; Day 3 = C,D,A,G,H,E; Day 4 = B,C,D,F,G,H).
- **Days 5–6 are long-block days**: four ~87-minute blocks (Day 5 = A,B,E,F; Day 6 = C,D,G,H).
- So **every block meets 4 of every 6 school days**: three short meetings and one long one.
- **L1 and L2 (10:33–10:58, 11:02–11:27) are a split lunch band.** This student has homeroom in L1 and lunch in L2 ("LUNCH/BREAK 2"). The naming suggests other students get the reverse, which would make homeroom a *mid-morning* event and not the start of the day most parents picture. That reverse assignment is inferred from the naming, not confirmed.
- **Cycles count rotations.** Every Day 1 starts a new numbered cycle (Cycle 1 … Cycle 19 by February). A "Day 0 – Opening Day Schedule" precedes Cycle 1.
- **Terms**: FY courses run all year. S1 and S2 courses swap at the semester line. In this schedule, block D changes from Philosophy (S1) to Phys Ed (S2), and blocks C and H (Cooking, Health, both S1) are **blank** in Q3/Q4.

Answering *"what class is she in at 9:15 on October 6th?"* takes **four** sources joined together. No document states the join:

1. District rotation calendar → Oct 6 is Day 4
2. Rotation legend (or the Bell grid) → Day 4 runs B, C, D, then F, G, H
3. Bell schedule → the second slot runs 8:31–9:28
4. Term + marking-period dates → Oct 6 is in S1, so block C is Science of Cooking

And if Oct 6 were an early-dismissal day, step 3 would need the early-dismissal bell times, which are only published by slot number.

## Semantically identical concepts, named differently

This is the core of the naming problem you noticed. Each row is **one concept**. The columns show what each source calls it.

| Concept | Genesis List print | Genesis Bell print | Genesis screens | District rotation PDF | School bell PDF / our `bell_periods` | Our schema |
|---|---|---|---|---|---|---|
| **Rotation day** (1–6) | digits in the `Days` column | column header `1`…`6` | **"Today's Cycle: 1"**, "Mon, 09/14 (1)", "1 Day Schedule" | "Day 1", and legend "Day 1 = …" | — | `ChildDayCycle.cycle_label`; calendar `Day N` items |
| **Rotation count** (1–19…) | — | — | — | **"Cycle 2"** | — | `hs_rotation` `cycle` |
| **Course block** (A–H, L1, L2) | `Per` | corner letter | letter above each block | legend letters | — | `ChildScheduleBlock.period` |
| **Clock slot** (1st, 2nd, … of the day) | — | row position (unlabeled) | — | — | **"1"…"6", "L1", "L2"** | `bell_periods[].name` |
| **Marking period** (~10 weeks) | — | **"Q1"…"Q4"** | "MP1", "Marking Period 1" | — | — | `ChildMarkingPeriod.label` ("MP1") |
| **Term** | `Sem`: FY / S1 / S2 | `FY`/`S1` glued onto the room | "FY" on the course card | — | — | `ChildScheduleBlock.term` |
| **Weekday** | bus table's `Days`: **MTWRF** | — | "Mon" | "14-Day" under a month header | — | — |

The collisions that actually cause mistakes:

- **"Cycle" means opposite things in two sources.** Genesis's "Today's Cycle: 1" is the *rotation day*. The district PDF's "Cycle 2" is the *count of rotations*. On Sept 14, Genesis says "Cycle 1" and the district says "Day 1 – Cycle 2". Both are correct, and they use the same word for different things. Our own model inherited Genesis's usage (`ChildDayCycle.cycle_label` holds a rotation day).
- **"1" means three different things.** In the Bell print it's a rotation *day* (column header). In the bell-schedule PDF and our `bell_periods` it's a clock *slot* (first slot of the day). In the List print's `Days` column it's a rotation day again. "Period 1" at East is not block A. It's whichever block has the first slot that day.
- **`Per` (period) holds a block letter, not a period.** The school's bell sheet uses "period" for clock slots. Genesis uses it for course blocks. Nobody at the school would confuse them, but every parent does.
- **One printout uses `Days` for two different things.** The course table's `Days` means rotation days (`123456`). The bus table directly below it uses `Days` for weekdays (`MTWRF`, with R for Thursday).
- **`Sem` holds "FY"**, which isn't a semester. **The Bell print says "Q1"; the gradebook for the same classes says "MP1".** No document says that S1 = MP1 + MP2. We inferred it from Q1 and Q2 printing identically.
- **L1/L2 are the only labels that mean the same thing as a block and as a slot**, and that's partly why our `period_number` mapping works for them and nothing else.

### The `Days 123456` column is actively misleading

The List print says every academic course meets on days `123456`. The Bell grid and the district legend both show every block meets on exactly **four** of the six. `Days` seems to mean "which rotation days this section is scheduled on" before the drop pattern is applied. Only the Bell print or the district legend shows the pattern. Anyone who reads the List print, which is the one with the bus info and the date, will think Geometry meets every day.

Related: Homeroom appears as two List rows, `1 3 5` and `2 4 6`, with the same room and the same teachers. The Bell print colors them differently. The split is invisible to the family and has no apparent meaning, so treat it as one daily homeroom. Meanwhile the **`Homeroom:` header field is blank on both printouts**, even though a Homeroom course row with a room exists.

## Formats (the same fact, written differently)

| Fact | Spellings seen |
|---|---|
| A time | `7:30AM-8:27AM` (Bell print), `7:30 AM - 8:27 AM` (Genesis screen), `06:54AM` (bus, zero-padded), `07:30` (our table) |
| A date | `09/20/2026` (List header), `09/14` (daily view, no year), `9/2/26` (grades), `9/02 to 11/10` (MP ranges, no year), `14-Day` under a `September` header in a `2026-2027` sheet (rotation PDF), `Sep 4, 2025` / `May 11` (Classroom) |
| A school | `Cherry Hill High School East(50)` (List, with the district's school code glued on), `Cherry Hill High School East` (Bell) |
| A teacher | `Scharff, Elizabeth M` (Last, First MI), `Pierlott, Marc`, `Borrelli/Squazzo` (co-taught: last names only, slash-joined), `Anthony Maniscalco` (Classroom), `Mr. Maniscalco` |
| A course | `ENG/LANG ARTS 2A`, `US HISTORY 1A`, `INTERMEDIATE GERMAN I A`. The trailing letters are a level or section marker we can't decode from the documents. Classroom names the same class differently again; `kids_view.course_key` joins them on the district course/section code |
| A term | `FY` in its own column (List) vs `Room: C203 FY` (Bell and Genesis screen) |

`kids_view.name_parts` already handles all four teacher shapes. The year-less dates are the same hazard as the due-date year bug in CLAUDE.md: a year has to be inferred from the Jul–Jun school year.

### If we ever parse the Bell print

Its text layer can't be used. It glues fields with no separator: `AGEOMETRY A` (block + title), `Room: B232 S17:30AM` (term `S1` + time `7:30AM`, which reads as "S17"), `S111:31AM` (`S1` + `11:31AM`), `THE ARTOF LIVING` (a lost space). Pages with a spilled row lose their column-6 header in the text. Like `hs_rotation.py`, it would need pdfplumber word coordinates, placing each cell by position. We shouldn't bother, though. Everything in it can be *derived* from the List data (block → course, term), the district legend, and the bell times, all of which we already have.

## A real gap this exposed: long-block days

`alembic/versions/0024_school_bell_periods.py` transcribes East/West's regular bell schedule as six 57-minute slots. Its comment says the clock times never vary, only which letter fills each slot. **The Bell print contradicts that for Days 5 and 6**: they run four blocks, 7:30–8:57, 9:01–10:29, 11:31–12:58, and 1:02–2:30.

Consequences today:

- **`school_today`'s "current period"** is computed from the regular table with no rotation-day input. So on a Day 5 or 6 (a third of all school days), the public Today card shows slot boundaries that don't exist. At 8:40 it says "Period 2 started 8:31" while every student is 70 minutes into a block that ends at 8:57.
- **`kids_view.right_now`** is fine for current/next, because it uses the child's own captured Genesis daily blocks. But its `period_number` lookup matches start times against the regular table, so on long-block days B (9:01) and F (1:02) get no period number.
- **Long-block days with early dismissal are completely unmodeled.** The rotation calendar has one: *Dec 4, "6 (Early Dismissal – Afternoon PD)"*. We have no timetable for a shortened Day 6, and neither printout contains one.

**Fixed for East** (migration `0046`), and surfaced in Today, as described in the next section. West shares the rotation sheet, but its long-block clock times aren't confirmed yet, so West gets the letters and a "long blocks" label with no clock times and no period chip. Showing nothing is better than showing wrong times.

## In the Today view

Everything here is school-wide. The letters and times are identical for every student at East, so the public Today card can show them without an account and without revealing anything about any one child's classes.

- **Header line:** `High school · Day 2 · D A B H E F` (plus `· long blocks` on Days 5–6).
- **Lettered timeline** under the header: one chip per slot (`D 7:30`, `A 8:31`, … with `L1`/`L2` narrower), with the current block highlighted. The period chip reads "A block · ends 9:28 AM" instead of "Period 2".
- **Next school day's configuration:** `Tomorrow: Day 3 · C D A G H E`. This is for the night-before check.
- **Week strip:** each day shows its letters under the day number, plus `long` on Days 5–6.

How it works: `hs_rotation_scan` already writes each day's letters into its `Day N` item (`Blocks A, B, E, F · Cycle 2`). `hs_rotation.blocks_from_description` reads them back, and `bell_schedule.lettered_day` zips them onto whichever bell variant has the same number of slots. That's `regular`, `long_block`, `early_dismissal`, or `delayed_opening`, chosen by day status. L1/L2 keep their own names. When no table fits (a long-block early dismissal), there's no timeline and no period chip. The long-block flag comes from the rotation (fewer letters than regular slots), not from whether the times are on file.

Still not built: **"next meets" per course** (item 2 below). It would need the student's own letter → course mapping, so it belongs in Kids view / Focus, not the public card.

## What a high schooler and their parents actually need to track

Most of what these documents contain is scheduling machinery the school needs and a family doesn't. Sorted by who uses it and how often:

### The student: daily, one glance, the night before

1. **Tomorrow's letter configuration.** Students, parents, and staff all refer to a day by the letters that meet ("Day 5 is A B E F", "a C-D-G-H day"), and that's the unit everyone tracks. The day number is only a key into it. Say whether it's a regular, long-block, or modified day (early dismissal, delayed opening, PSAT, exam day), because that decides the clock times.
2. **Today's blocks, in order, with times.** Not the six-column grid. Just the four or six letters that actually meet today. A student maps letters to their own classes without help.
3. **When each class next meets.** This is the most useful derived fact, and **no document gives it.** Teachers set work "due next class", and with a 4-of-6 drop rotation plus weekends and holidays, "next class" can be anywhere from 1 to 5+ calendar days away. Once you have the legend and the rotation calendar, it's pure arithmetic: *"Chemistry: next meets Thursday (Day 5, long block)"*. It's also what makes a Classroom due date meaningful: something due Thursday for a class that doesn't meet Wednesday effectively has to be done Tuesday night.
4. **Bus time**, and only on days when it changes: early dismissal, delayed opening.
5. What's due and what's missing (already covered by Kids view / Focus).

The student doesn't need cycle numbers, term codes, or `Days 123456`. Room numbers matter for about the first two weeks, and after that only for a substitute or a room change.

### The parent: weekly and per marking period

1. **Days that change pickup or supervision**: no school, early dismissal, delayed opening. The day's letters matter too, because they're the shorthand the household already uses ("it's a C-D-G-H day, so PE today").
2. **Marking-period boundaries, as deadlines.** When MP1 ends (11/10 here), missing MP1 work stops being recoverable, and grades lock toward a report card. This is where "missed deadline" parent frustration concentrates at the high school level. The dates exist in Genesis ("MP1 9/02 to 11/10"). They're just never presented as a deadline.
3. **The semester changeover (~Jan 28 here).** Three S1 courses end, PE starts (gear, a new teacher), and two blocks go blank. The family should know ahead of time whether those blanks are study halls/free periods or spring electives that haven't been assigned yet. **A blank cell on a printout doesn't say which**, which is the same rule `late_credit` follows: unknown must stay distinguishable from known.
4. **Teachers per course, with an email that works.** Co-taught classes (`Borrelli/Squazzo`) mean two people, and the parent needs to know both exist.
5. **Grade trend within the current marking period**, not the full list of scores.

The parent almost never needs the time grid, the lunch wave, or room numbers.

### Nobody in the family needs

- **Cycle numbers** (Cycle 1…19). These are an internal counter, probably for teachers' "once per cycle" planning.
- The **homeroom 1-3-5 / 2-4-6 split**.
- **Quarter pages that repeat** (Q1 = Q2, Q3 = Q4). A family needs *two* schedules, fall and spring, not four.

## Proposed canonical vocabulary for schoolz

To keep this from spreading further into our own code and UI, use one word per concept and translate at the boundary. Parsers keep the source's own label in the raw data, and the canonical name is used everywhere else.

| Canonical | Means | Shown to families as | Source spellings it absorbs |
|---|---|---|---|
| `rotation_day` | 1–6 | "Day 5" | Genesis "Cycle", Bell column header, `Days` digits, district "Day N" |
| `rotation_cycle` | 1, 2, 3… | (not shown) | district "Cycle N" |
| `block` | A–H, L1, L2 | the letter. That's how everyone at the school says it | Genesis `Per`, Bell corner letter |
| `slot` | 1st…6th position in the day | the clock time, never a number | bell-schedule "Period 1…6" |
| `marking_period` | MP1–MP4 | "Marking period 1 (ends Nov 10)" | Bell "Q1", Genesis "MP1"/"Marking Period 1" |
| `term` | full_year / semester_1 / semester_2 | "All year" / "Fall" / "Spring" | `FY`/`S1`/`S2` |
| `day_type` | regular / long_block / early_dismissal / delayed_opening / closed | "Long blocks", "Early dismissal" | bell-schedule variants + rotation calendar notes |

Places in our own code that currently use a word for the wrong concept, to rename when they're next touched (not worth a dedicated migration): `ChildDayCycle`/`cycle_label` (holds a rotation day), `ChildScheduleBlock.period` (holds a block), and `kids_view.right_now`'s `period_number` (holds a slot).

## Actionable list

1. ~~**Model long-block days**~~: done for East (see below). West's long-block times and a long-block early-dismissal timetable (Dec 4) still need confirming with the schools.
2. **Compute "next meets" per course** from the rotation calendar and the legend. This is the single most useful fact missing from every document.
3. **Present marking-period ends and the semester changeover as dated deadlines** in the family calendar, not only as grade-page metadata.
4. **Never show `Days 123456` or cycle numbers to a family.** Translate the first to "meets 4 of every 6 days" and drop the second. **Do show letters.** They're the shared language, and showing them needs no student data at all.
5. **Treat a blank Bell-print cell as unknown**, not free, until the family or the school says otherwise.
6. **For the district conversation**: one term for "Cycle" vs "Day", one term for marking periods across the printout and the gradebook, a date on the Bell print, the drop pattern in the List print's `Days` column, and a published long-block early-dismissal timetable.
