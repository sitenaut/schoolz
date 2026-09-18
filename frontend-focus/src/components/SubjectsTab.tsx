import { shortCourseName, tileColor } from "../courses";
import type { CourseProgress, ScheduleResponse } from "../types";

/** The tile grid from the mockup - and, by design, where "the future" is.
 *
 * The dashboard is blind past the next school day; anything further out
 * is reachable only by tapping a subject here. That is deliberate: a
 * different tab is what gives permission to ignore next week tonight.
 *
 * Tiles come from /bucket3/progress rather than the schedule, because the
 * badge is the point: it's the count of things actually outstanding in
 * that class. The schedule is used only to label a tile with its period
 * letter, and only on an exact course-name match.
 *
 * That match usually fails, and the reason is worth knowing: Genesis calls
 * the class "GEOMETRY A" while Classroom calls it "GEOM A Per A 2026-27
 * 210-1", and the two are linked by the district code embedded in the
 * Classroom name - which the schedule rows don't carry. Guessing across
 * that gap would mean fuzzy name matching, which this codebase
 * deliberately avoids; an unlabelled tile is the honest outcome. */
export function SubjectsTab({
  courses,
  schedule,
  onOpenCourse,
}: {
  courses: CourseProgress[];
  schedule: ScheduleResponse | null;
  onOpenCourse: (course: CourseProgress) => void;
}) {
  if (courses.length === 0) {
    return (
      <div className="empty-state">
        <h2>No classes yet</h2>
        <p>Import a Genesis gradebook or a Classroom page to see subjects here.</p>
      </div>
    );
  }

  const periodByName = new Map<string, string>();
  for (const block of schedule?.list_view ?? []) {
    if (!periodByName.has(block.course_name)) periodByName.set(block.course_name, block.period);
  }

  return (
    <div className="tile-grid">
      {courses.map((course) => {
        const open = course.missing + course.due_soon;
        const period = periodByName.get(course.course_name);
        return (
          <button
            type="button"
            key={course.course_key}
            className={`tile ${tileColor(course.course_key)}`}
            onClick={() => onOpenCourse(course)}
            aria-label={`${shortCourseName(course.course_name)}${open ? `, ${open} outstanding` : ""}`}
          >
            {period && <span className="tile-period">Per. {period}</span>}
            <span className="tile-name">{shortCourseName(course.course_name)}</span>
            {open > 0 && <span className="tile-badge">{open}</span>}
            {course.grade_percent !== null && <span className="tile-grade">{Math.round(course.grade_percent)}%</span>}
          </button>
        );
      })}
    </div>
  );
}
