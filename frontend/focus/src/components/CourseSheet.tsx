import { useState } from "react";
import { daysFromToday, dueLabel, shortCourseName } from "../courses";
import type { CourseProgress, TodoItem } from "../types";
import { Capped } from "./Capped";
import { Sheet } from "./Sheet";

/** Where the future lives.
 *
 * The dashboard is deliberately blind past the next school day, so this
 * is the only place next week's essay exists. Putting it behind a tap on
 * a subject tile - a different tab, a different screen - is what gives
 * permission to ignore it tonight. Grouped by distance, nearest first. */
export function CourseSheet({
  course,
  items,
  todayIso,
  onClose,
  onOpenItem,
  onToggle,
}: {
  course: CourseProgress;
  items: TodoItem[];
  todayIso: string;
  onClose: () => void;
  onOpenItem: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  const [showDone, setShowDone] = useState(false);

  const missing = items.filter((i) => i.category === "missing");
  const upcoming = items.filter((i) => i.category === "due" && i.due_date);
  const thisWeek = upcoming.filter((i) => daysFromToday(i.due_date!, todayIso) <= 7);
  const later = upcoming.filter((i) => daysFromToday(i.due_date!, todayIso) > 7);
  const undated = items.filter((i) => i.category === "no_due_date");
  const done = items.filter((i) => i.category === "done");

  return (
    <Sheet onClose={onClose} label={course.course_name}>
      <h2 className="sheet-title">{shortCourseName(course.course_name)}</h2>
      <p className="sheet-course">
        {course.teacher_name ?? "Teacher unknown"}
        {course.grade_percent !== null && ` · ${Math.round(course.grade_percent)}%`}
      </p>

      <ItemList label="Missing" items={missing} tone="missed" todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />
      <ItemList label="This week" items={thisWeek} todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />
      <ItemList label="Later" items={later} todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />
      <ItemList label="No due date" items={undated} todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />

      {missing.length + upcoming.length + undated.length === 0 && (
        <p className="sheet-empty">Nothing outstanding in this class.</p>
      )}

      {done.length > 0 && (
        <section className="finished">
          <button type="button" className="finished-toggle" onClick={() => setShowDone((s) => !s)}>
            {showDone ? "Hide" : "Show"} finished ({done.length})
          </button>
          {showDone && <ItemList label={null} items={done} todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />}
        </section>
      )}
    </Sheet>
  );
}

function ItemList({
  label,
  items,
  tone,
  todayIso,
  onOpen,
  onToggle,
}: {
  label: string | null;
  items: TodoItem[];
  tone?: "missed";
  todayIso: string;
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section className="sheet-section">
      {label && <h3 className={`group-heading${tone ? ` ${tone}` : ""}`}>{label}</h3>}
      <Capped items={items} cap={5} noun="tasks">
        {(visible) => (
          <ul className="sheet-list">
            {visible.map((item) => (
              <li key={item.id} className={`sheet-item${item.done ? " is-done" : ""}`}>
                <button type="button" className="sheet-item-open" onClick={() => onOpen(item)}>
                  <span className="sheet-item-title">{item.title}</span>
                  {item.due_date && <span className="due">{dueLabel(item.due_date, todayIso)}</span>}
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
              </li>
            ))}
          </ul>
        )}
      </Capped>
    </section>
  );
}
