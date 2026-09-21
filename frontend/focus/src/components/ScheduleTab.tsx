import { useState } from "react";
import { courseColorProps } from "../courses";
import type { ScheduleResponse } from "../types";

/** Today's class schedule and the full-year course list, both from Genesis
 * (schoolz-web's own ScheduleTab in KidsDetailPage.tsx renders the same two
 * lists as a plain HTML table - this is the same data, in Focus's own
 * card/chip visual language instead of a table, since that's what every
 * other tab here uses).
 *
 * Blocks carry only course_name, never course_key (bucket3.py's
 * ChildScheduleBlock has no course_key column - see SubjectsTab's own note
 * on why the Genesis/Classroom name match usually fails), so colors here
 * are keyed by name rather than the code+section key Focus/Subjects use.
 * Two tabs can therefore color the same class differently; that's an
 * existing, documented gap, not something introduced here. */
export function ScheduleTab({ schedule }: { schedule: ScheduleResponse | null }) {
  const [showFullYear, setShowFullYear] = useState(false);

  if (!schedule || (schedule.daily.length === 0 && schedule.list_view.length === 0)) {
    return (
      <div className="empty-state">
        <h2>No schedule yet</h2>
        <p>Capture a Genesis student-summary page to see today's classes here.</p>
      </div>
    );
  }

  return (
    <>
      {schedule.daily.length > 0 && (
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
