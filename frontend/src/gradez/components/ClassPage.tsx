import { Link } from "react-router-dom";
import { courseColorProps, daysFromToday, dueLabel, sortMissingByRecency } from "../courses";
import { genesisDate, genesisKey, genesisOrder, initials, isGraded, lateLine, mailtoHref, markingPeriodName, percentText, policySentence, scoreText } from "../format";
import type { CourseColorOverrides } from "../lib/coursePreferences";
import type { Grades, LatePolicy, ScheduleResponse, TodoItem, TodoResponse } from "../types";
import { Capped } from "./Capped";
import type { ClassRow } from "./GradesTab";
import { IconChevronRight, IconPencil } from "./icons";

const LIST_CAP = 5;

function dueLine(item: TodoItem, todayIso: string): string {
  const label = dueLabel(item.due_date, todayIso);
  if (!label) return "No due date";
  return label === "Today" || label === "Tomorrow" ? `Due ${label.toLowerCase()}` : `Due ${label}`;
}

/** "Period 1" for the class Genesis schedules under that name, if any. */
function periodLabel(schedule: ScheduleResponse | null, genesisName: string | null): string | null {
  if (!schedule || !genesisName) return null;
  const period = schedule.list_view.find((b) => b.course_name === genesisName)?.period;
  if (!period) return null;
  return /^\w{1,3}$/.test(period) ? `Period ${period}` : period;
}

/** Everything behind one class's grade: the rule for late work, what is
 * still to do, and what has been graded. The Grades tab stays current. */
export function ClassPage({
  row,
  period,
  isCurrentPeriod,
  todo,
  grades,
  schedule,
  policy,
  postCount,
  todayIso,
  courseColors,
  teachersTo,
  onOpen,
  onToggle,
  onEditAppearance,
  onEditPolicy,
}: {
  row: ClassRow;
  period: string | null;
  isCurrentPeriod: boolean;
  todo: TodoResponse | null;
  grades: Grades | null;
  schedule: ScheduleResponse | null;
  policy: LatePolicy | null;
  postCount: number;
  todayIso: string;
  courseColors: CourseColorOverrides;
  teachersTo: string;
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
  onEditAppearance: () => void;
  onEditPolicy: () => void;
}) {
  const key = row.course_key;
  const { className, style } = courseColorProps(key, courseColors[key]);
  const mine = (i: TodoItem) => i.course_key === key;

  const missing = sortMissingByRecency((todo?.missing ?? []).filter(mine));
  // No rule on file keeps late work on To do: only a known zero is "too late".
  const stillCounts = missing.filter((i) => !i.late_credit || i.late_credit.accepted);
  const tooLate = missing.filter((i) => i.late_credit && !i.late_credit.accepted);
  const upcoming = (todo?.due ?? []).filter((i) => mine(i) && i.due_date);
  const thisWeek = upcoming.filter((i) => daysFromToday(i.due_date!, todayIso) <= 7);
  const later = upcoming.filter((i) => daysFromToday(i.due_date!, todayIso) > 7);
  const undated = (todo?.no_due_date ?? []).filter(mine);
  const outstanding = missing.length + upcoming.length + undated.length;

  const genesisName = grades?.course_grades.find((g) => genesisKey(g) === key)?.course_name ?? null;
  // Graded work newest first, then what is listed but not graded yet.
  const entries = (grades?.entries ?? [])
    .filter((e) => genesisKey(e) === key && (!period || e.marking_period === period))
    .sort((a, b) => Number(isGraded(b)) - Number(isGraded(a)) || genesisOrder(b) - genesisOrder(a));
  const where = [row.teacher_name, periodLabel(schedule, genesisName)].filter(Boolean).join(" · ");
  const mail = mailtoHref(row.teacher_emails, row.name);
  const low = row.grade_percent != null && row.grade_percent < 50;

  return (
    <>
      <header className="gz-class-head">
        <span className={`gz-tile gz-tile-lg ${className}`} style={style} aria-hidden="true">
          {initials(row.name)}
        </span>
        <div className="gz-class-title">
          <h1>{row.name}</h1>
          {where && <p>{where}</p>}
        </div>
        <button
          type="button"
          className="gz-icon-btn"
          aria-label="Rename or recolor this class. Only you see the change."
          onClick={onEditAppearance}
        >
          <IconPencil />
        </button>
      </header>

      <div className="gz-content">
        <section className="gz-card gz-grade-card">
          <div>
            <p className="gz-row-sub">Grade{period ? `, ${markingPeriodName(period).toLowerCase()}` : ""}</p>
            {row.grade_percent != null ? (
              <p className={`gz-grade-big${low ? " gz-is-low" : ""}`}>{percentText(row.grade_percent)}</p>
            ) : (
              <p className="gz-no-grade">No grade yet</p>
            )}
          </div>
          {mail && (
            <a className="gz-btn" href={mail}>
              Email {row.teacher_name}
            </a>
          )}
        </section>

        <section className="gz-card gz-rule">
          <div className="gz-rule-head">
            <h2>Late-work rule</h2>
            <button type="button" className="gz-text-btn" onClick={onEditPolicy}>
              {policy ? "Change" : "Add"}
            </button>
          </div>
          {policy ? (
            <>
              <p className="gz-rule-text">{policySentence(policy, todayIso)}</p>
              <p className="gz-note">Typed in from the syllabus. It decides which late work is still worth doing.</p>
            </>
          ) : (
            <>
              <p className="gz-rule-text">No rule on file yet.</p>
              <p className="gz-note">
                Until there is one, all late work in this class stays on To do. Add what the syllabus says about late work.
              </p>
            </>
          )}
        </section>

        {isCurrentPeriod && (
          <section className="gz-section">
            <header className="gz-section-head">
              <h2>Work</h2>
            </header>
            {outstanding === 0 && <p className="gz-note">Nothing outstanding in this class.</p>}
            <WorkGroup label="This week" items={thisWeek} sub={(i) => dueLine(i, todayIso)} onOpen={onOpen} onToggle={onToggle} />
            <WorkGroup
              label="Missing, still counts"
              tone="late"
              items={stillCounts}
              sub={(i) => lateLine(i.late_credit, i.due_date, todayIso)}
              onOpen={onOpen}
              onToggle={onToggle}
            />
            <WorkGroup label="Later" items={later} sub={(i) => dueLine(i, todayIso)} onOpen={onOpen} onToggle={onToggle} />
            <WorkGroup label="No due date" items={undated} sub={() => null} onOpen={onOpen} onToggle={onToggle} />
            {tooLate.length > 0 && (
              <div className="gz-group">
                <h3 className="gz-group-heading">Too late for credit</h3>
                <Capped items={tooLate} cap={LIST_CAP} noun="tasks">
                  {(visible) => (
                    <ul className="gz-card gz-list">
                      {visible.map((item) => (
                        <li key={item.id} className="gz-late-row">
                          <button type="button" className="gz-task-body" onClick={() => onOpen(item)}>
                            <span className="gz-row-title gz-is-light">{item.title}</span>
                            <span className="gz-row-sub">{lateLine(item.late_credit, item.due_date, todayIso)}</span>
                          </button>
                          <button type="button" className="gz-text-btn" onClick={() => onOpen(item)}>
                            A teacher said they'd still take this
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </Capped>
              </div>
            )}
          </section>
        )}

        {entries.length > 0 && (
          <section className="gz-section">
            <header className="gz-section-head">
              <h2>
                {!period ? "Graded" : isCurrentPeriod ? "Graded this marking period" : `Graded in ${markingPeriodName(period).toLowerCase()}`}
              </h2>
              {!isCurrentPeriod && period && <p>To do covers the current marking period only.</p>}
            </header>
            <Capped items={entries} cap={LIST_CAP * 2} noun="entries">
              {(visible) => (
                <ul className="gz-card gz-list">
                  {visible.map((e) => (
                    <li key={e.external_uid} className="gz-graded-row">
                      <span className="gz-row-main">
                        <span className="gz-row-title gz-is-light">{e.title}</span>
                        <span className="gz-row-sub">{isGraded(e) ? genesisDate(e.weekday_date) : "Not graded yet"}</span>
                      </span>
                      {isGraded(e) ? (
                        <span className="gz-score">{scoreText(e)}</span>
                      ) : (
                        e.score_possible != null && <span className="gz-no-grade">{e.score_possible} pts</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Capped>
          </section>
        )}

        {postCount > 0 && (
          <Link className="gz-card gz-link-row" to={teachersTo}>
            <span>
              Posts from {row.teacher_name ?? "this class"} ({postCount})
            </span>
            <IconChevronRight />
          </Link>
        )}
      </div>
    </>
  );
}

function WorkGroup({
  label,
  tone,
  items,
  sub,
  onOpen,
  onToggle,
}: {
  label: string;
  tone?: "late";
  items: TodoItem[];
  sub: (item: TodoItem) => string | null;
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className={`gz-group${tone ? " gz-is-late" : ""}`}>
      <h3 className="gz-group-heading">{label}</h3>
      <Capped items={items} cap={LIST_CAP} noun="tasks">
        {(visible) => (
          <ul className="gz-card gz-list">
            {visible.map((item) => {
              const line = sub(item);
              return (
                <li key={item.id} className="gz-work-row">
                  <label className="gz-task-check">
                    <input
                      type="checkbox"
                      checked={item.done}
                      onChange={(e) => onToggle(item, e.target.checked)}
                      aria-label={`Mark ${item.title} done`}
                    />
                  </label>
                  <button type="button" className="gz-task-body" onClick={() => onOpen(item)}>
                    <span className="gz-row-title gz-is-light">{item.title}</span>
                    {line && <span className="gz-row-sub">{line}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Capped>
    </div>
  );
}
