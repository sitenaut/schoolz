import { useState } from "react";
import {
  courseColorProps,
  daysFromToday,
  displayCourseName,
  dueLabel,
  horizon,
  sortDueByPoints,
  sortMissingByRecency,
} from "../courses";
import type { CourseColorOverrides, CourseNameOverrides } from "../lib/coursePreferences";
import { BACKPACK_CAPTURE_STORE_URL, type Freshness } from "../lib/freshness";
import type { TodoItem, TodoResponse, TodoView } from "../types";
import { Capped } from "./Capped";
import { InboxZero } from "./InboxZero";

// The rule of 3 to 5: a list this short is finishable, and a list that
// keeps going isn't. Up next never grows past its cap without being asked.
const UP_NEXT_CAP = 4;
const ATTENTION_CAP = 3;
const LATER_CAP = 5;

// Ticking something off moves it out of today's set on the server (a late
// item has no due date inside the horizon), which would shrink the progress
// bar's total instead of filling it. Remembering what was ticked today keeps
// the bar honest for the rest of the day. The key's name is older than
// Gradez's; keeping it carries today's ticks across the move.
function clearedKey(todayIso: string): string {
  return `focus_cleared_${todayIso}`;
}

function readCleared(todayIso: string): Set<string> {
  try {
    const raw = localStorage.getItem(clearedKey(todayIso));
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function writeCleared(todayIso: string, ids: Set<string>) {
  try {
    localStorage.setItem(clearedKey(todayIso), JSON.stringify([...ids]));
  } catch {
    /* storage unavailable */
  }
}

type Shared = {
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
  courseColors: CourseColorOverrides;
  courseNames: CourseNameOverrides;
};

/** What to work on now.
 *
 * "What's next" is today, the next school day, and late work that still
 * earns credit, capped. "Whole week" is the same list with the rest of the
 * week, what's further out and undated work underneath, for a parent
 * planning ahead. Late work past its class's cutoff
 * is on neither: it is on the class page, where the teacher's exception is. */
export function TodoTab({
  todo,
  fresh,
  todayIso,
  view,
  onView,
  onRetry,
  ...shared
}: {
  todo: TodoResponse | null;
  fresh: Freshness | null;
  todayIso: string;
  view: TodoView;
  onView: (view: TodoView) => void;
  onRetry: () => void;
} & Shared) {
  const [cleared, setCleared] = useState(() => readCleared(todayIso));
  const [showFinished, setShowFinished] = useState(false);

  if (fresh?.kind === "never") return <GetStarted />;
  if (!todo) {
    return (
      <div className="gz-empty-state">
        <h2>Couldn't load assignments</h2>
        <p>Nothing is wrong with the schoolwork itself. Check the connection and try again.</p>
        <button type="button" className="gz-btn" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  const toggle = (item: TodoItem, done: boolean) => {
    const next = new Set(cleared);
    if (done) next.add(item.id);
    else next.delete(item.id);
    setCleared(next);
    writeCleared(todayIso, next);
    shared.onToggle(item, done);
  };
  const rows = { ...shared, onToggle: toggle };

  const h = horizon(todayIso);
  const inHorizon = (d: string | null) => d === h.today || d === h.next;
  const dueToday = sortDueByPoints(todo.due.filter((i) => i.due_date === h.today));
  const dueNext = sortDueByPoints(todo.due.filter((i) => i.due_date === h.next));
  const dueSoon = [...dueToday, ...dueNext];
  // No rule on file is "we don't know", and unknown stays on the list: only
  // a known zero takes late work off it.
  const missing = sortMissingByRecency(todo.missing.filter((i) => !i.late_credit || i.late_credit.accepted));

  // Up next is never left half empty while late work waits: the newest
  // late items fill the open places, and the rest go under Needs attention.
  const backfillCount = Math.max(0, UP_NEXT_CAP - dueSoon.length);
  const backlogFill = missing.slice(0, backfillCount);
  const upNext = [...dueSoon, ...backlogFill];
  const attention = missing.slice(backfillCount);

  const finished = todo.done.filter((i) => inHorizon(i.due_date) || cleared.has(i.id));
  const total = dueSoon.length + finished.length;
  const pct = total ? Math.round((finished.length * 100) / total) : 0;
  const allClear = dueSoon.length + missing.length === 0;
  const caption =
    total === 0
      ? missing.length > 0
        ? "Nothing due right now"
        : "Nothing on your plate"
      : `${finished.length} of ${total} done`;

  const later = todo.due.filter((i) => i.due_date && i.due_date > h.next);
  const thisWeek = later.filter((i) => daysFromToday(i.due_date!, todayIso) <= 7);
  const comingUp = later.filter((i) => daysFromToday(i.due_date!, todayIso) > 7);

  return (
    <>
      <div className="gz-segmented" role="group" aria-label="How much to show">
        <button type="button" aria-pressed={view === "next"} onClick={() => onView("next")}>
          What's next
        </button>
        <button type="button" aria-pressed={view === "week"} onClick={() => onView("week")}>
          Whole week
        </button>
      </div>

      <section className="gz-card gz-progress" aria-label="Today's progress">
        <div className="gz-progress-row">
          <span>Today's progress</span>
          <span className="gz-progress-count">{caption}</span>
        </div>
        <div className="gz-bar" role="img" aria-label={`${finished.length} of ${total} done`}>
          <span style={{ width: `${pct}%` }} />
        </div>
      </section>

      {allClear ? (
        <InboxZero finished={finished.length} asOf={fresh?.kind === "stale" ? fresh.ago : null} />
      ) : (
        <>
          {upNext.length > 0 && (
            <section className="gz-section">
              <header className="gz-section-head">
                <h2>Up next</h2>
                <p>Due today or the next school day. Do these first.</p>
              </header>
              <Capped items={upNext} cap={UP_NEXT_CAP} noun="tasks">
                {(visible) => (
                  <>
                    <TaskGroup label="Today" items={visible.filter((i) => dueToday.includes(i))} {...rows} />
                    <TaskGroup label={h.nextLabel} items={visible.filter((i) => dueNext.includes(i))} {...rows} />
                    <TaskGroup
                      label={dueSoon.length > 0 ? "Also up next" : "Late, still worth doing"}
                      items={visible.filter((i) => backlogFill.includes(i))}
                      {...rows}
                    />
                  </>
                )}
              </Capped>
            </section>
          )}

          {attention.length > 0 && (
            <section className="gz-attention">
              <header className="gz-section-head">
                <h2>Needs attention</h2>
                <p>Late, but turning it in still earns credit.</p>
              </header>
              <Capped items={attention} cap={ATTENTION_CAP} noun="missing">
                {(visible) => <TaskList items={visible} pill="Missed" {...rows} />}
              </Capped>
            </section>
          )}
        </>
      )}

      {view === "week" && (
        <>
          {thisWeek.length > 0 && (
            <section className="gz-section">
              <header className="gz-section-head">
                <h2>Later this week</h2>
                <p>Not due yet. Nothing is lost by leaving these for now.</p>
              </header>
              {groupByDue(thisWeek).map(([due, items]) => (
                <TaskGroup key={due} label={dueLabel(due, todayIso)} items={items} {...rows} />
              ))}
            </section>
          )}
          {comingUp.length > 0 && (
            <section className="gz-section">
              <header className="gz-section-head">
                <h2>Coming up</h2>
                <p>Due more than a week from now.</p>
              </header>
              <Capped items={comingUp} cap={LATER_CAP} noun="tasks">
                {(visible) => <TaskList items={visible} due={todayIso} {...rows} />}
              </Capped>
            </section>
          )}
          {todo.no_due_date.length > 0 && (
            <section className="gz-section">
              <header className="gz-section-head">
                <h2>No due date</h2>
                <p>Classroom lists these with no date on them.</p>
              </header>
              <Capped items={todo.no_due_date} cap={LATER_CAP} noun="tasks">
                {(visible) => <TaskList items={visible} {...rows} />}
              </Capped>
            </section>
          )}
        </>
      )}

      {finished.length > 0 && (
        <>
          <button type="button" className="gz-btn gz-btn-wide" aria-expanded={showFinished} onClick={() => setShowFinished((s) => !s)}>
            {showFinished ? "Hide" : "Show"} finished ({finished.length})
          </button>
          {showFinished && <TaskList items={finished} {...rows} />}
        </>
      )}
    </>
  );
}

function groupByDue(items: TodoItem[]): [string, TodoItem[]][] {
  const groups = new Map<string, TodoItem[]>();
  for (const item of items) {
    const due = item.due_date ?? "";
    groups.set(due, [...(groups.get(due) ?? []), item]);
  }
  return [...groups.entries()];
}

function TaskGroup({ label, items, ...rows }: { label: string | null; items: TodoItem[] } & Shared) {
  if (items.length === 0) return null;
  return (
    <div className="gz-group">
      {label && <h3 className="gz-group-heading">{label}</h3>}
      <TaskList items={items} {...rows} />
    </div>
  );
}

function TaskList({
  items,
  pill,
  due,
  ...rows
}: {
  items: TodoItem[];
  pill?: string;
  /** Today's date, when each row should say when it is due. */
  due?: string;
} & Shared) {
  return (
    <ul className="gz-task-list">
      {items.map((item) => (
        <li key={item.id}>
          <TaskCard item={item} pill={pill} due={due} {...rows} />
        </li>
      ))}
    </ul>
  );
}

/** Subject, title, checkbox. Nothing else: the due day is the heading above,
 * and every other detail waits in the sheet the card opens.
 *
 * Named and colored by course_key, with the reader's own rename or recolor
 * applied, the same way every other tab does it. */
function TaskCard({
  item,
  pill,
  due,
  onOpen,
  onToggle,
  courseColors,
  courseNames,
}: { item: TodoItem; pill?: string; due?: string } & Shared) {
  const course = item.course_name ? displayCourseName(item.course_name, courseNames[item.course_key]) : null;
  const { className, style } = courseColorProps(item.course_key, courseColors[item.course_key]);
  const when = due && item.due_date ? dueLabel(item.due_date, due) : null;
  return (
    <div className={`gz-task${item.done ? " gz-is-done" : ""}`}>
      <label className="gz-task-check">
        <input
          type="checkbox"
          checked={item.done}
          onChange={(e) => onToggle(item, e.target.checked)}
          aria-label={`Mark ${item.title} done`}
        />
      </label>
      <button type="button" className="gz-task-body" onClick={() => onOpen(item)}>
        {(course || when) && (
          <span className="gz-task-subject">
            {course && <span className={`gz-dot ${className}`} style={style} aria-hidden="true" />}
            {[course, when].filter(Boolean).join(" · ")}
          </span>
        )}
        <span className="gz-task-title">{item.title}</span>
      </button>
      {pill && !item.done && <span className="gz-pill gz-pill-missed">{pill}</span>}
    </div>
  );
}

/** Shown until Backpack Capture has sent anything for this child. */
function GetStarted() {
  return (
    <section className="gz-empty-state gz-get-started">
      <h2>Bring in assignments and grades</h2>
      <ol className="gz-starter-steps">
        <li>On a computer, add Backpack Capture to Chrome.</li>
        <li>
          Open it and press <strong>Connect to schoolz</strong>, then <strong>Connect</strong> on the page it opens.
        </li>
        <li>
          Press <strong>Update now</strong>.
        </li>
      </ol>
      <a className="gz-primary" href={BACKPACK_CAPTURE_STORE_URL} target="_blank" rel="noopener noreferrer">
        Get Backpack Capture
      </a>
      <p className="gz-sheet-note">
        It reads Google Classroom in your own Chrome while you're signed in, and keeps it up to date every few hours.
      </p>
    </section>
  );
}
