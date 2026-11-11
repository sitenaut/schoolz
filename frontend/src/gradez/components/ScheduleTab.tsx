import { useState } from "react";
import { courseColorProps, displayCourseName } from "../courses";
import { clockLabel, clockMinutes, genesisKey, mailtoHref, plural, weekdayName } from "../format";
import type { CourseColorOverrides, CourseNameOverrides } from "../lib/coursePreferences";
import type { Grades, NowBlock, RightNow, ScheduleBlock, ScheduleDay, ScheduleResponse } from "../types";
import { IconChevronRight } from "./icons";

type Naming = {
  /** Genesis course name -> the key every other tab knows the class by. */
  keys: Map<string, string>;
  courseColors: CourseColorOverrides;
  courseNames: CourseNameOverrides;
};

function nameOf(courseName: string, n: Naming): string {
  const key = n.keys.get(courseName);
  return displayCourseName(courseName, key ? n.courseNames[key] : undefined);
}

// A class Genesis schedules but hasn't graded yet has no key to look up, so
// it is colored by its name: steady, though not the color To do would pick.
function colorOf(courseName: string, n: Naming) {
  const key = n.keys.get(courseName);
  return courseColorProps(key ?? courseName, key ? n.courseColors[key] : undefined);
}

function roomLabel(room: string | null): string | null {
  if (!room) return null;
  return /^\d+[A-Za-z]?$/.test(room) ? `Room ${room}` : room;
}

function periodLabel(b: NowBlock): string {
  if (b.period_number) return /^\d+$/.test(b.period_number) ? `Period ${b.period_number}` : b.period_number;
  return /^[A-Za-z]$/.test(b.period) ? `Block ${b.period}` : b.period;
}

/** Where the child is right now, and which classes meet on any school day.
 *
 * The days are computed on the server from the Genesis list view and the
 * district's rotation calendar, so they are right on days nobody captured
 * Genesis's daily page. "Right now" is the one part that needs today's
 * captured page, and it stays away rather than guess from an older one. */
export function ScheduleTab({
  schedule,
  rightNow,
  grades,
  todayIso,
  now,
  courseColors,
  courseNames,
}: {
  schedule: ScheduleResponse | null;
  rightNow: RightNow | null;
  grades: Grades | null;
  todayIso: string;
  /** The clock as of the last load or return to the page, never a timer. */
  now: number;
  courseColors: CourseColorOverrides;
  courseNames: CourseNameOverrides;
}) {
  const [showFullYear, setShowFullYear] = useState(false);
  const [picked, setPicked] = useState(0);
  const days = schedule?.days ?? [];
  const day = days[Math.min(picked, days.length - 1)];

  const naming: Naming = { keys: new Map(), courseColors, courseNames };
  for (const g of grades?.course_grades ?? []) {
    if (g.course_name) naming.keys.set(g.course_name, genesisKey(g));
  }

  const live = rightNow && !rightNow.stale && (rightNow.current || (rightNow.next && !rightNow.school_day_over)) ? rightNow : null;

  if (!schedule || (schedule.daily.length === 0 && schedule.list_view.length === 0 && days.length === 0)) {
    return (
      <div className="gz-empty-state">
        <h2>No schedule yet</h2>
        <p>Classes appear here once Backpack Capture has sent the Genesis schedule.</p>
      </div>
    );
  }

  const at = new Date(now);
  const nowMinutes = at.getHours() * 60 + at.getMinutes();

  return (
    <>
      {live && <NowCard rightNow={live} naming={naming} />}

      {day && (
        <>
          {days.length > 1 && (
            <div className="gz-day-picker" role="group" aria-label="Pick a school day">
              {days.map((d, i) => (
                <button type="button" key={d.date} aria-pressed={d === day} aria-label={weekdayName(d.date)} onClick={() => setPicked(i)}>
                  {d.date === todayIso ? "Today" : d.weekday}
                </button>
              ))}
            </div>
          )}
          <ComputedDay day={day} naming={naming} nowMinutes={day.date === todayIso ? nowMinutes : null} />
        </>
      )}

      {!day && schedule.daily.length > 0 && (
        <section className="gz-section">
          <header className="gz-section-head">
            <h2>{schedule.cycle_date ? `Schedule for ${schedule.cycle_date}` : "Today's schedule"}</h2>
            {schedule.cycle_label && <p>Cycle {schedule.cycle_label}</p>}
          </header>
          <BlockList blocks={schedule.daily} showDays={false} naming={naming} />
        </section>
      )}

      {schedule.list_view.length > 0 && (
        <>
          <button type="button" className="gz-link-btn" aria-expanded={showFullYear} onClick={() => setShowFullYear((s) => !s)}>
            {showFullYear ? "Hide the full-year schedule" : "Full-year schedule"}
            {!showFullYear && <IconChevronRight />}
          </button>
          {showFullYear && <BlockList blocks={schedule.list_view} showDays naming={naming} />}
        </>
      )}
    </>
  );
}

function NowCard({ rightNow, naming }: { rightNow: RightNow; naming: Naming }) {
  const block = (rightNow.current ?? rightNow.next)!;
  const inSession = Boolean(rightNow.current);
  const index = rightNow.blocks.findIndex((b) => b.period === block.period);
  const following = index >= 0 ? rightNow.blocks.slice(index + 1, index + 3) : [];
  const where = [roomLabel(block.room), block.teacher].filter(Boolean).join(" · ");
  const mail = mailtoHref(block.teacher_emails);
  const total = (block.minutes_in ?? 0) + (block.minutes_left ?? 0);
  const left = [
    inSession && block.minutes_left != null && `${plural(block.minutes_left, "minute")} left.`,
    inSession && block.time_end && `Ends ${clockLabel(block.time_end)}.`,
    !inSession && block.time_start && `Starts ${clockLabel(block.time_start)}.`,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section className="gz-now" aria-label="Right now">
      <p className="gz-now-label">
        {inSession ? "Right now" : "Up next"} · {periodLabel(block)}
      </p>
      <p className="gz-now-class">{nameOf(block.course_name, naming)}</p>
      {where && <p className="gz-now-where">{where}</p>}
      {inSession && total > 0 && (
        <div
          className="gz-bar gz-bar-now"
          role="progressbar"
          aria-label={`${periodLabel(block)} progress`}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={block.minutes_in ?? 0}
        >
          <span style={{ width: `${Math.round(((block.minutes_in ?? 0) * 100) / total)}%` }} />
        </div>
      )}
      {left && <p className="gz-now-left">{left}</p>}
      {following.length > 0 && (
        <p className="gz-now-where">
          {inSession ? "Next" : "Then"}: {following.map((b) => nameOf(b.course_name, naming)).join(", then ")}.
        </p>
      )}
      {mail && (
        <a className="gz-btn gz-btn-now" href={mail}>
          Email {block.teacher}
        </a>
      )}
    </section>
  );
}

/** One school day: the blocks that meet, in clock order, each filled with
 * this student's class for the current semester. */
function ComputedDay({ day, naming, nowMinutes }: { day: ScheduleDay; naming: Naming; nowMinutes: number | null }) {
  const letters = day.blocks.filter((b) => /^[A-H]$/.test(b.name)).map((b) => b.name);
  const detail = [
    day.rotation_day,
    letters.join(" "),
    day.long_blocks && "long blocks",
    day.status === "early_dismissal" && "early dismissal",
    day.status === "delayed" && "delayed opening",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <section className="gz-section">
      <header className="gz-section-head">
        <h2>{weekdayName(day.date)}</h2>
        <p>{detail || "No rotation on file for this day"}</p>
      </header>
      {day.blocks.length === 0 && day.rotation_day && <p className="gz-note">Nothing on file for {day.rotation_day} yet.</p>}
      {!day.timed && letters.length > 0 && <p className="gz-note">No published bell times for this day, so this is the class order only.</p>}
      {day.blocks.length > 0 && (
        <ul className="gz-card gz-list">
          {day.blocks.map((b) => {
            const start = clockMinutes(b.start_label);
            const end = clockMinutes(b.end_label);
            const isNow = nowMinutes != null && start != null && end != null && start <= nowMinutes && nowMinutes < end;
            const color = b.course_name ? colorOf(b.course_name, naming) : null;
            return (
              <li key={b.name} className={`gz-sched-row${isNow ? " gz-is-now" : ""}${b.course_name ? "" : " gz-is-free"}`}>
                <span className="gz-sched-time">{b.start_label ? `${clockLabel(b.start_label)} – ${clockLabel(b.end_label)}` : b.name}</span>
                <span className="gz-sched-class">
                  {color && <span className={`gz-dot ${color.className}`} style={color.style} aria-hidden="true" />}
                  {b.course_name ? nameOf(b.course_name, naming) : /^[A-H]$/.test(b.name) ? "Nothing scheduled" : b.name}
                  {isNow && <span className="gz-pill gz-pill-now">Now</span>}
                </span>
                {b.room && <span className="gz-sched-room">{roomLabel(b.room)}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** Genesis's own rows: the captured day when no rotation calendar exists, and the full year. */
function BlockList({ blocks, showDays, naming }: { blocks: ScheduleBlock[]; showDays: boolean; naming: Naming }) {
  return (
    <ul className="gz-card gz-list">
      {blocks.map((b) => {
        const color = colorOf(b.course_name, naming);
        const meta = [b.teacher, roomLabel(b.room), showDays ? b.days : null].filter(Boolean).join(" · ");
        return (
          <li key={`${b.period}-${b.schedule_date ?? b.term ?? ""}`} className="gz-sched-row gz-is-tall">
            <span className="gz-sched-time">
              {b.time_start ? `${clockLabel(b.time_start)}${b.time_end ? ` – ${clockLabel(b.time_end)}` : ""}` : b.period}
            </span>
            <span className="gz-row-main">
              <span className="gz-sched-class">
                <span className={`gz-dot ${color.className}`} style={color.style} aria-hidden="true" />
                {nameOf(b.course_name, naming)}
              </span>
              {meta && <span className="gz-row-sub">{meta}</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
