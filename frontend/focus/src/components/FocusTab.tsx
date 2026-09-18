import { useState } from "react";
import { horizon, shortCourseName, tileColor } from "../courses";
import type { TodoItem, TodoResponse } from "../types";
import { Capped } from "./Capped";
import { InboxZero } from "./InboxZero";

// The Rule of 3 to 5. Four is the most cards that fit above the fold on a
// phone in a two-column grid, and three attention rows is the most that
// still reads as "handle these" rather than "here is a wall".
const UP_NEXT_CAP = 4;
const ATTENTION_CAP = 3;

/** Ids checked off through THIS screen today.
 *
 * The daily progress bar has to reward clearing a missing item, but once
 * it's marked done the backend correctly moves it out of `missing` and its
 * due date is two weeks old - so nothing about the item itself says it was
 * finished today. This per-device set fills that gap. It's a convenience,
 * not a record: a fresh browser just shows the bar without those credits. */
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

function writeCleared(todayIso: string, ids: Set<string>): void {
  try {
    localStorage.setItem(clearedKey(todayIso), JSON.stringify([...ids]));
  } catch {
    /* storage unavailable - the bar just won't remember across reloads */
  }
}

/** The bouncer. Nothing gets on this screen unless it is missing, due
 * today, or due the next school day. Everything else lives in Subjects
 * until its day comes - that separation is the whole design, not a
 * filter setting. */
export function FocusTab({
  todo,
  todayIso,
  onOpen,
  onToggle,
}: {
  todo: TodoResponse | null;
  todayIso: string;
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  const [cleared, setCleared] = useState(() => readCleared(todayIso));
  const [showFinished, setShowFinished] = useState(false);

  const toggle = (item: TodoItem, done: boolean) => {
    const next = new Set(cleared);
    if (done) next.add(item.id);
    else next.delete(item.id);
    setCleared(next);
    writeCleared(todayIso, next);
    onToggle(item, done);
  };

  if (!todo) {
    return (
      <div className="empty-state">
        <h2>Nothing imported yet</h2>
        <p>Capture a Genesis or Classroom page with the extension, then import it in schoolz.</p>
      </div>
    );
  }

  const h = horizon(todayIso);
  const inHorizon = (d: string | null) => d === h.today || d === h.next;
  const dueToday = todo.due.filter((i) => i.due_date === h.today);
  const dueNext = todo.due.filter((i) => i.due_date === h.next);
  const upNext = [...dueToday, ...dueNext];
  const missing = todo.missing;

  // Progress is the 3-to-5 things, not the mountain. Its denominator is the
  // horizon (due today / next school day) plus anything already finished
  // toward it. Unfinished MISSING work is deliberately left out: with 13
  // missing in the denominator, finishing tonight's four cards moved the
  // bar to 23% - the same failure as showing marking-period totals, just
  // smaller. Clearing a missing item is credited as a bonus instead: it
  // raises both numbers, so 4/4 becomes 5/5, and the bar never asks her
  // to dig out of a hole before it will fill.
  const finished = todo.done.filter((i) => inHorizon(i.due_date) || cleared.has(i.id));
  const total = upNext.length + finished.length;
  const pct = total ? Math.round((finished.length * 100) / total) : 0;
  const remaining = missing.length + upNext.length;
  const allClear = remaining === 0;
  const caption =
    total === 0
      ? missing.length > 0
        ? "No deadlines today - clear what's missing"
        : "Nothing on your plate"
      : `${finished.length} of ${total} done`;

  return (
    <>
      <section className={`card${allClear && total > 0 ? " complete" : ""}`}>
        <h2 className="card-label">Today's progress</h2>
        <div className="progress-track" role="img" aria-label={`${finished.length} of ${total} done`}>
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <p className="progress-caption">{caption}</p>
      </section>

      {allClear ? (
        <InboxZero finished={finished.length} />
      ) : (
        <>
          {missing.length > 0 && (
            <section className="card attention">
              <h2 className="card-label">Needs attention</h2>
              <Capped items={missing} cap={ATTENTION_CAP} noun="missing">
                {(visible) => (
                  <ul className="attention-list">
                    {visible.map((item) => (
                      <li key={item.id}>
                        <button type="button" className="attention-row" onClick={() => onOpen(item)}>
                          <span className="attention-title">{item.title}</span>
                          <span className="pill missed">Missed</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Capped>
            </section>
          )}

          <h2 className="section-heading">Up next</h2>
          {upNext.length === 0 ? (
            <div className="empty-state small">
              <p>Nothing due today or {h.nextLabel.toLowerCase()}. Clear the missing work above and you're done.</p>
            </div>
          ) : (
            <Capped items={upNext} cap={UP_NEXT_CAP} noun="tasks">
              {(visible) => {
                const today = visible.filter((i) => i.due_date === h.today);
                const next = visible.filter((i) => i.due_date === h.next);
                return (
                  <>
                    {today.length > 0 && <TaskGroup label="Today" items={today} onOpen={onOpen} onToggle={toggle} />}
                    {next.length > 0 && <TaskGroup label={h.nextLabel} items={next} onOpen={onOpen} onToggle={toggle} />}
                  </>
                );
              }}
            </Capped>
          )}
        </>
      )}

      {finished.length > 0 && (
        <section className="finished">
          <button type="button" className="finished-toggle" onClick={() => setShowFinished((s) => !s)}>
            {showFinished ? "Hide" : "Show"} finished ({finished.length})
          </button>
          {showFinished && <TaskGroup label={null} items={finished} onOpen={onOpen} onToggle={toggle} />}
        </section>
      )}
    </>
  );
}

function TaskGroup({
  label,
  items,
  onOpen,
  onToggle,
}: {
  label: string | null;
  items: TodoItem[];
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  return (
    <div className="task-group">
      {label && <h3 className="group-heading">{label}</h3>}
      <div className="task-grid">
        {items.map((item) => (
          <TaskCard key={item.id} item={item} onOpen={onOpen} onToggle={onToggle} />
        ))}
      </div>
    </div>
  );
}

/** Subject, title, checkbox. Nothing else - the due date lives in the
 * group heading above, and every other detail waits in the sheet. */
function TaskCard({
  item,
  onOpen,
  onToggle,
}: {
  item: TodoItem;
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  const course = item.course_name ? shortCourseName(item.course_name) : null;
  return (
    <article className={`task-card${item.done ? " is-done" : ""}`}>
      <button type="button" className="task-open" onClick={() => onOpen(item)}>
        {course && <span className={`chip ${tileColor(item.course_name ?? course)}`}>{course}</span>}
        <h4 className="task-title">{item.title}</h4>
      </button>
      <label className="check">
        <input
          type="checkbox"
          checked={item.done}
          onChange={(e) => onToggle(item, e.target.checked)}
          aria-label={`Mark ${item.title} done`}
        />
        <span className="box" aria-hidden="true" />
      </label>
    </article>
  );
}
