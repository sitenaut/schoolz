import { courseColorProps, shortCourseName } from "../courses";
import type { CourseColorOverrides } from "../lib/courseColors";
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
  courseColors,
}: {
  courses: CourseProgress[];
  schedule: ScheduleResponse | null;
  onOpenCourse: (course: CourseProgress) => void;
  courseColors: CourseColorOverrides;
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
        const name = shortCourseName(course.course_name);
        const initials = name
          .split(/\s+/)
          .filter(Boolean)
          .slice(0, 2)
          .map((w) => w[0])
          .join("")
          .toUpperCase();
        const { className, style } = courseColorProps(course.course_key, courseColors[course.course_key]);
        return (
          <button
            type="button"
            key={course.course_key}
            className={`tile ${className}`}
            style={style}
            onClick={() => onOpenCourse(course)}
            aria-label={`${name}${open ? `, ${open} outstanding` : ""}`}
          >
            <div className="tile-top">
              <span className="tile-avatar">{initials}</span>
              {period && <span className="tile-period">Per. {period}</span>}
            </div>
            <span className="tile-name">{name}</span>
            <div className="tile-bottom">
              {course.grade_percent !== null && <span className="tile-grade">{Math.round(course.grade_percent)}%</span>}
              {open > 0 && <span className="tile-badge">{open}</span>}
            </div>
          </button>
        );
      })}
    </div>
  );
}
