import { useState } from "react";
import { dueLabel, shortCourseName } from "../courses";
import type { CourseProgress, LatePolicy, TodoItem, TodoResponse } from "../types";
import { LatePolicyEditor, describePolicy } from "./LatePolicyEditor";

/** The deliberate opposite of the dashboard's "bouncer": every course,
 * every grade, every assignment in every bucket - missing, due, no due
 * date, and done - with no caps and no time-blindness. The design-
 * constraints memory for FocusTab is explicit that the dashboard must
 * stay capped and only show today/next-school-day; this tab exists so a
 * parent or a kid who specifically wants the full Classroom-style picture
 * has somewhere to get it, without that pulling the caps off the
 * dashboard itself. Same data already loaded for Focus/Subjects - no
 * extra request.
 *
 * This is also where work past its late cutoff lives. The Focus tab drops
 * those entirely (nothing can be earned, so putting them in front of
 * someone trying to work is guilt with no action attached) - but dropping
 * them everywhere would be dishonest, and a parent may well want to see
 * them. Here they're visible, grouped, and quiet. */
export function DetailsTab({
  todo,
  courses,
  todayIso,
  policies,
  studentId,
  onSavePolicy,
  onDeletePolicy,
  onOpen,
  onToggle,
}: {
  todo: TodoResponse | null;
  courses: CourseProgress[];
  todayIso: string;
  policies: LatePolicy[];
  studentId: string | null;
  onSavePolicy: (policy: Partial<LatePolicy> & { course_key: string }) => Promise<boolean>;
  onDeletePolicy: (courseKey: string) => Promise<void>;
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);

  if (!todo || courses.length === 0) {
    return (
      <div className="empty-state">
        <h2>Nothing to show yet</h2>
        <p>Import a Genesis gradebook or a Classroom page to see full details here.</p>
      </div>
    );
  }

  const allItems = [...todo.missing, ...todo.due, ...todo.no_due_date, ...todo.done];
  const byCourse = new Map<string, TodoItem[]>();
  for (const item of allItems) {
    const key = item.course_name ?? "Other";
    byCourse.set(key, [...(byCourse.get(key) ?? []), item]);
  }
  const policyFor = (courseKey: string) => policies.find((p) => p.course_key === courseKey) ?? null;

  return (
    <>
      {courses.map((course) => {
        const items = byCourse.get(course.course_name) ?? [];
        const policy = policyFor(course.course_key);
        return (
          <section className="card" key={course.course_key}>
            <h3 className="card-label">
              {shortCourseName(course.course_name)}
              {course.grade_percent !== null && ` · ${Math.round(course.grade_percent)}%`}
              {course.teacher_name && ` · ${course.teacher_name}`}
            </h3>

            <div className="policy-row">
              <span className="policy-current">
                {policy ? describePolicy(policy) : "No late-work rule on file"}
              </span>
              {studentId && editing !== course.course_key && (
                <button type="button" className="policy-edit" onClick={() => setEditing(course.course_key)}>
                  {policy ? "Change" : "Add"}
                </button>
              )}
            </div>
            {studentId && editing === course.course_key && (
              <LatePolicyEditor
                courseKey={course.course_key}
                courseName={course.course_name}
                studentId={studentId}
                existing={policy}
                onSave={onSavePolicy}
                onDelete={onDeletePolicy}
                onClose={() => setEditing(null)}
              />
            )}

            {items.length === 0 ? (
              <p className="sheet-empty">Nothing recorded.</p>
            ) : (
              <ul className="sheet-list">
                {items.map((item) => {
                  const closed = item.late_credit && !item.late_credit.accepted;
                  return (
                    <li key={item.id} className={`sheet-item${item.done ? " is-done" : ""}`}>
                      <button type="button" className="sheet-item-open" onClick={() => onOpen(item)}>
                        <span className="sheet-item-title">
                          {item.category === "missing" && !item.done ? `⚠ ${item.title}` : item.title}
                        </span>
                        {closed ? (
                          <span className="due">past cutoff</span>
                        ) : item.due_date ? (
                          <span className="due">{dueLabel(item.due_date, todayIso)}</span>
                        ) : item.grade?.percent !== null && item.grade?.percent !== undefined ? (
                          <span className="due">{Math.round(item.grade.percent)}%</span>
                        ) : null}
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
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </>
  );
}
