import { useState } from "react";
import { displayCourseName, dueLabel } from "../courses";
import type { CourseNameOverrides } from "../lib/coursePreferences";
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
  courseNames,
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
  courseNames: CourseNameOverrides;
}) {
  const [editing, setEditing] = useState<string | null>(null);

  const allItems = todo ? [...todo.missing, ...todo.due, ...todo.no_due_date, ...todo.done] : [];
  if (!todo || (courses.length === 0 && allItems.length === 0)) {
    return (
      <div className="empty-state">
        <h2>Nothing to show yet</h2>
        <p>Import a Genesis gradebook or a Classroom page to see full details here.</p>
      </div>
    );
  }

  // Grouped by course_key, the identity /progress uses too. Grouping by name
  // and drawing cards only from /progress lost every item /progress has no
  // row for: a class with only undated work, and work with no class at all.
  const byCourse = new Map<string, TodoItem[]>();
  for (const item of allItems) {
    byCourse.set(item.course_key, [...(byCourse.get(item.course_key) ?? []), item]);
  }
  const policyFor = (courseKey: string) => policies.find((p) => p.course_key === courseKey) ?? null;
  const cards: { course_key: string; course_name: string | null; progress: CourseProgress | null }[] = courses.map((course) => ({
    course_key: course.course_key,
    course_name: course.course_name,
    progress: course,
  }));
  const shown = new Set(courses.map((c) => c.course_key));
  for (const [courseKey, items] of byCourse) {
    if (!shown.has(courseKey)) cards.push({ course_key: courseKey, course_name: items[0].course_name, progress: null });
  }

  return (
    <>
      {cards.map(({ course_key: courseKey, course_name: courseName, progress: course }) => {
        const items = byCourse.get(courseKey) ?? [];
        const policy = policyFor(courseKey);
        // A late-work rule needs a class to belong to.
        const canEditPolicy = Boolean(studentId && courseName);
        return (
          <section className="card" key={courseKey}>
            <h3 className="card-label">
              {courseName ? displayCourseName(courseName, courseNames[courseKey]) : "Other"}
              {course && course.grade_percent !== null && ` · ${Math.round(course.grade_percent)}%`}
              {course?.teacher_name && ` · ${course.teacher_name}`}
            </h3>

            {courseName && (
              <div className="policy-row">
                <span className="policy-current">
                  {policy ? describePolicy(policy) : "No late-work rule on file"}
                </span>
                {canEditPolicy && editing !== courseKey && (
                  <button type="button" className="policy-edit" onClick={() => setEditing(courseKey)}>
                    {policy ? "Change" : "Add"}
                  </button>
                )}
              </div>
            )}
            {studentId && courseName && editing === courseKey && (
              <LatePolicyEditor
                courseKey={courseKey}
                courseName={courseName}
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
                        {/* Grade shown whenever one exists, independent of
                            due-date status - a matched Genesis grade doesn't
                            stop being true just because the item also has a
                            due date on file (see TaskModal's own note on
                            this same match). */}
                        {(() => {
                          const badge = [
                            closed ? "past cutoff" : item.due_date ? dueLabel(item.due_date, todayIso) : null,
                            item.grade?.percent !== null && item.grade?.percent !== undefined
                              ? `${Math.round(item.grade.percent)}%`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ");
                          return badge ? <span className="due">{badge}</span> : null;
                        })()}
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
