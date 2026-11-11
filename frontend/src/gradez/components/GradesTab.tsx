import { useState } from "react";
import { Link } from "react-router-dom";
import { courseColorProps, displayCourseName } from "../courses";
import { genesisDate, genesisKey, genesisOrder, initials, isGraded, mailtoHref, markingPeriodName, percentText, plural, scoreText } from "../format";
import type { CourseColorOverrides, CourseNameOverrides } from "../lib/coursePreferences";
import type { CourseProgress, GradeEntry, Grades } from "../types";
import { IconChevronRight } from "./icons";

const RECENT_CAP = 5;
const LOW_GRADE = 50;

/** One class as the list shows it, whichever marking period is picked. */
export type ClassRow = {
  course_key: string;
  name: string;
  teacher_name: string | null;
  teacher_emails: string[];
  grade_percent: number | null;
  /** Null for a past marking period: To do only knows the current one. */
  missing: number | null;
};

/** Every marking period Genesis has reported, newest first. */
export function markingPeriodLabels(grades: Grades | null): string[] {
  if (!grades) return [];
  const byStart = [...grades.marking_periods].sort((a, b) => (a.start_date < b.start_date ? 1 : -1)).map((p) => p.label);
  const extra = [...new Set(grades.course_grades.map((g) => g.marking_period))].filter((l) => !byStart.includes(l));
  return [...byStart, ...extra.sort().reverse()];
}

/** The class list for one marking period. The current one comes from
 * /progress, which already joins Classroom's classes to Genesis's; an
 * earlier one is Genesis's own rows, named the way the current list names
 * the same class. */
export function classRows(
  period: string | null,
  currentPeriod: string | null,
  courses: CourseProgress[],
  grades: Grades | null,
  courseNames: CourseNameOverrides,
): ClassRow[] {
  if (!period || !grades || period === currentPeriod) {
    return courses.map((c) => ({
      course_key: c.course_key,
      name: displayCourseName(c.course_name ?? c.course_key, courseNames[c.course_key]),
      teacher_name: c.teacher_name,
      teacher_emails: c.teacher_emails,
      grade_percent: c.grade_percent,
      missing: c.missing,
    }));
  }
  // Genesis prints "0.00%" for a class with nothing graded: no grade, not a failing one.
  const graded = new Set(grades.entries.filter((e) => e.marking_period === period && isGraded(e)).map(genesisKey));
  return grades.course_grades
    .filter((g) => g.marking_period === period)
    .map((g) => {
      const key = genesisKey(g);
      const now = courses.find((c) => c.course_key === key);
      return {
        course_key: key,
        name: displayCourseName(now?.course_name ?? g.course_name ?? key, courseNames[key]),
        teacher_name: now?.teacher_name ?? null,
        teacher_emails: now?.teacher_emails ?? [],
        grade_percent: graded.has(key) ? g.grade_percent : null,
        missing: null,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Graded work of one marking period, newest mark first. */
export function gradedEntries(grades: Grades | null, period: string | null): GradeEntry[] {
  if (!grades) return [];
  return grades.entries
    .filter((e) => isGraded(e) && (!period || e.marking_period === period))
    .sort((a, b) => {
      if (a.graded_at && b.graded_at && a.graded_at !== b.graded_at) return a.graded_at < b.graded_at ? 1 : -1;
      return genesisOrder(b) - genesisOrder(a);
    });
}

/** How each class is going, and where to step in. */
export function GradesTab({
  courses,
  grades,
  period,
  periods,
  currentPeriod,
  onPeriod,
  classTo,
  courseColors,
  courseNames,
}: {
  courses: CourseProgress[];
  grades: Grades | null;
  period: string | null;
  periods: string[];
  currentPeriod: string | null;
  onPeriod: (label: string) => void;
  /** Where one class's page is: a link, so Back returns to this list. */
  classTo: (courseKey: string) => string;
  courseColors: CourseColorOverrides;
  courseNames: CourseNameOverrides;
}) {
  const [showAll, setShowAll] = useState(false);
  const rows = classRows(period, currentPeriod, courses, grades, courseNames);
  const low = rows.filter((r) => r.grade_percent != null && r.grade_percent < LOW_GRADE);
  const graded = gradedEntries(grades, period);
  const nameOf = (e: GradeEntry) => rows.find((r) => r.course_key === genesisKey(e))?.name ?? e.course_name ?? genesisKey(e);

  if (rows.length === 0) {
    return (
      <div className="gz-empty-state">
        <h2>No classes yet</h2>
        <p>Classes appear here once Backpack Capture has sent Google Classroom or the Genesis gradebook.</p>
      </div>
    );
  }

  return (
    <>
      {periods.length > 1 && (
        <div className="gz-chips" role="group" aria-label="Marking period">
          {periods.map((label) => (
            <button type="button" key={label} aria-pressed={label === period} onClick={() => onPeriod(label)}>
              {markingPeriodName(label)}
            </button>
          ))}
        </div>
      )}

      {low.map((row) => {
        const mail = mailtoHref(row.teacher_emails, `Makeup work in ${row.name}`);
        return (
          <section className="gz-warn" key={row.course_key} aria-label={`${row.name} is below 50%`}>
            <strong>{row.name} is below 50%</strong>
            <p>Ask the teacher whether makeup work is possible before the marking period ends.</p>
            {mail && (
              <a className="gz-btn" href={mail}>
                Email {row.teacher_name}
              </a>
            )}
          </section>
        );
      })}

      <ul className="gz-card gz-list" aria-label="Classes">
        {rows.map((row) => {
          const { className, style } = courseColorProps(row.course_key, courseColors[row.course_key]);
          return (
            <li key={row.course_key}>
              <Link className="gz-class-row" to={classTo(row.course_key)} state={{ fromGrades: true }}>
                <span className={`gz-tile ${className}`} style={style} aria-hidden="true">
                  {initials(row.name)}
                </span>
                <span className="gz-row-main">
                  <span className="gz-row-title">{row.name}</span>
                  <span className="gz-row-sub">
                    {row.teacher_name}
                    {row.missing ? <span className="gz-pill gz-pill-missed">{row.missing} missing</span> : null}
                  </span>
                </span>
                {row.grade_percent != null ? (
                  <span className={`gz-grade${row.grade_percent < LOW_GRADE ? " gz-is-low" : ""}`}>{percentText(row.grade_percent)}</span>
                ) : (
                  <span className="gz-no-grade">No grade yet</span>
                )}
                <IconChevronRight />
              </Link>
            </li>
          );
        })}
      </ul>

      {graded.length > 0 && (
        <section className="gz-section">
          <header className="gz-section-head">
            <h2>Recently graded</h2>
            <p>The newest marks from the Genesis gradebook.</p>
          </header>
          <ul className="gz-card gz-list">
            {(showAll ? graded : graded.slice(0, RECENT_CAP)).map((e) => (
              <li key={e.external_uid} className="gz-graded-row">
                <span className="gz-row-main">
                  <span className="gz-row-title gz-is-light">{e.title}</span>
                  <span className="gz-row-sub">
                    {nameOf(e)} · {genesisDate(e.weekday_date)}
                  </span>
                </span>
                <span className="gz-score">{scoreText(e)}</span>
              </li>
            ))}
          </ul>
          {graded.length > RECENT_CAP && (
            <button type="button" className="gz-link-btn" aria-expanded={showAll} onClick={() => setShowAll((s) => !s)}>
              {showAll ? "Show only the newest" : `All graded work this marking period (${graded.length})`}
            </button>
          )}
        </section>
      )}
      {grades && grades.entries.length === 0 && grades.course_grades.length === 0 && (
        <p className="gz-note">
          Grades appear once Backpack Capture has sent the Genesis gradebook. {plural(rows.length, "class", "classes")} so far, from Google
          Classroom.
        </p>
      )}
    </>
  );
}
