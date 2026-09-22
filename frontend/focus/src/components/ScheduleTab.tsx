import { useState } from "react";
import { courseColorProps, dueLabel } from "../courses";
import type { ScheduleDay, ScheduleResponse } from "../types";

/** The next few school days' classes, computed server-side from the Genesis
 * list view + district rotation calendar (services/kids_schedule.py), so it
 * works on days nobody captured Genesis's daily page. The captured daily view
 * is only the fallback when no rotation calendar exists; the full-year list
 * stays behind a toggle.
 *
 * Blocks carry only course_name, never course_key (bucket3.py's
 * ChildScheduleBlock has no course_key column - see SubjectsTab's own note
 * on why the Genesis/Classroom name match usually fails), so colors here
 * are keyed by name rather than the code+section key Focus/Subjects use.
 * Two tabs can therefore color the same class differently; that's an
 * existing, documented gap, not something introduced here. */
export function ScheduleTab({ schedule, todayIso }: { schedule: ScheduleResponse | null; todayIso: string }) {
  const [showFullYear, setShowFullYear] = useState(false);
  const [picked, setPicked] = useState(0);
  const days = schedule?.days ?? [];
  const day = days[Math.min(picked, days.length - 1)];

  if (!schedule || (schedule.daily.length === 0 && schedule.list_view.length === 0 && days.length === 0)) {
    return (
      <div className="empty-state">
        <h2>No schedule yet</h2>
        <p>Capture a Genesis student-summary page to see today's classes here.</p>
      </div>
    );
  }

  return (
    <>
      {day && (
        <section className="card">
          <div className="day-picker" role="tablist" aria-label="School day">
            {days.map((d, i) => (
              <button
                type="button"
                role="tab"
                aria-selected={d === day}
                className={`day-pick${d === day ? " is-on" : ""}`}
                key={d.date}
                onClick={() => setPicked(i)}
              >
                {dueLabel(d.date, todayIso)}
              </button>
            ))}
          </div>
          <ComputedDay day={day} />
        </section>
      )}

      {!day && schedule.daily.length > 0 && (
        <section className="card">
          <h2 className="card-label">
            {schedule.cycle_date ? `Schedule for ${schedule.cycle_date}` : "Today's schedule"}
            {schedule.cycle_label && ` · Cycle ${schedule.cycle_label}`}
          </h2>
          <ScheduleList blocks={schedule.daily} showDays={false} />
        </section>
      )}

      {schedule.list_view.length > 0 && (
        <section className="card">
          <button type="button" className="finished-toggle" onClick={() => setShowFullYear((s) => !s)}>
            {showFullYear ? "Hide" : "Show"} full-year schedule
          </button>
          {showFullYear && <ScheduleList blocks={schedule.list_view} showDays />}
        </section>
      )}
    </>
  );
}

/** One computed school day: the letters that meet, in clock order, each
 * filled with this student's course for the current semester. */
function ComputedDay({ day }: { day: ScheduleDay }) {
  const letters = day.blocks.filter((b) => /^[A-H]$/.test(b.name)).map((b) => b.name);
  const heading = [day.rotation_day, letters.join(" "), day.long_blocks && "long blocks", day.status === "early_dismissal" && "early dismissal", day.status === "delayed" && "delayed opening"]
    .filter(Boolean)
    .join(" · ");
  return (
    <>
      <h2 className="card-label">{heading || "No rotation on file for this day"}</h2>
      {day.blocks.length === 0 && day.rotation_day && <p className="schedule-note">Nothing on file for {day.rotation_day} yet.</p>}
      {!day.timed && letters.length > 0 && <p className="schedule-note">No published bell times for this day, so this is the class order only.</p>}
      <ul className="schedule-list">
        {day.blocks.map((b) => {
          const { className, style } = courseColorProps(b.course_name ?? b.name);
          return (
            <li key={b.name} className={`schedule-row${b.course_name ? "" : " is-empty"}`}>
              <span className={`schedule-period ${className}`} style={style}>
                {b.name}
              </span>
              <span className="schedule-main">
                <span className="schedule-course">{b.course_name ?? "Nothing scheduled"}</span>
                {(b.teacher || b.room) && <span className="schedule-meta">{[b.teacher, b.room].filter(Boolean).join(" · ")}</span>}
              </span>
              {b.start_label && (
                <span className="schedule-time">
                  {b.start_label} – {b.end_label}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function ScheduleList({
  blocks,
  showDays,
}: {
  blocks: ScheduleResponse["daily"];
  showDays: boolean;
}) {
  return (
    <ul className="schedule-list">
      {blocks.map((b) => {
        const { className, style } = courseColorProps(b.course_name);
        return (
          <li key={`${b.period}-${b.schedule_date ?? b.term ?? ""}`} className="schedule-row">
            <span className={`schedule-period ${className}`} style={style}>
              {b.period}
            </span>
            <span className="schedule-main">
              <span className="schedule-course">{b.course_name}</span>
              <span className="schedule-meta">
                {[b.teacher, b.room, showDays ? b.days : null].filter(Boolean).join(" · ") || " "}
              </span>
            </span>
            {(b.time_start || b.time_end) && (
              <span className="schedule-time">
                {b.time_start}
                {b.time_start && b.time_end ? " – " : ""}
                {b.time_end}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
