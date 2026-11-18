// A class's grade over time, rebuilt from its graded Genesis entries. No
// grade history is stored (child_course_grades keeps only the latest), so
// the line is the points each mark adds up to, counted the way Genesis
// counts them: Missing is a zero, Exempt doesn't count. A class that weighs
// categories (tests over homework) ends somewhere other than its Genesis
// grade, and the chart says so rather than pretending.
import type { GradeEntry } from "./types";

export type TrendMark = {
  entry: GradeEntry;
  /** What the one assignment scored, 0-100+ (extra credit goes past 100). */
  percent: number;
  missing: boolean;
};

export type TrendDay = {
  /** ISO date the marks are due on. */
  date: string;
  marks: TrendMark[];
  /** Points earned over points possible, everything up to and including this day. */
  grade: number | null;
};

/** "Mon 11/9" -> "2026-11-09". Genesis prints no year, and a school year
 * runs July to June, so the year comes from today's place in it. */
export function genesisIsoDate(weekdayDate: string, todayIso: string): string | null {
  const match = /(\d{1,2})\/(\d{1,2})$/.exec(weekdayDate.trim());
  const [ty, tm] = todayIso.split("-").map(Number);
  if (!match || !ty || !tm) return null;
  const month = Number(match[1]);
  const day = Number(match[2]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const startYear = tm >= 7 ? ty : ty - 1;
  const year = month >= 7 ? startYear : startYear + 1;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

const isMissing = (e: GradeEntry) => e.status === "Missing" && e.score_earned == null;

/** The assignment's own percent, or null when it has none to plot. */
function markPercent(e: GradeEntry): number | null {
  if (e.status === "Exempt") return null;
  if (isMissing(e)) return 0;
  if (e.score_earned != null && e.score_possible) return (100 * e.score_earned) / e.score_possible;
  return e.percent;
}

/** What one entry adds to the running total, or null when Genesis wouldn't
 * count it (Exempt, ungraded, a mark with no points to weigh). */
function points(e: GradeEntry): { earned: number; possible: number } | null {
  if (e.status === "Exempt") return null;
  if (isMissing(e)) return e.score_possible != null ? { earned: 0, possible: e.score_possible } : null;
  if (e.score_earned != null && e.score_possible != null) return { earned: e.score_earned, possible: e.score_possible };
  return null;
}

/** One class's graded entries (one marking period) as days in order, each
 * with its marks and the grade so far. */
export function gradeTrend(entries: GradeEntry[], todayIso: string): TrendDay[] {
  const byDate = new Map<string, GradeEntry[]>();
  for (const e of entries) {
    const date = genesisIsoDate(e.weekday_date, todayIso);
    if (!date) continue;
    byDate.set(date, [...(byDate.get(date) ?? []), e]);
  }
  let earned = 0;
  let possible = 0;
  const days: TrendDay[] = [];
  for (const date of [...byDate.keys()].sort()) {
    const marks: TrendMark[] = [];
    let counted = false;
    for (const e of byDate.get(date)!) {
      const pts = points(e);
      if (pts) {
        earned += pts.earned;
        possible += pts.possible;
        counted = true;
      }
      const percent = markPercent(e);
      if (percent != null) marks.push({ entry: e, percent, missing: isMissing(e) });
    }
    if (marks.length === 0 && !counted) continue;
    days.push({ date, marks, grade: possible > 0 ? (100 * earned) / possible : null });
  }
  return days;
}

/** The last grade the line reaches, to set against Genesis's own. */
export function lastGrade(days: TrendDay[]): number | null {
  for (let i = days.length - 1; i >= 0; i--) if (days[i].grade != null) return days[i].grade;
  return null;
}

/** Whether Genesis's grade is off from the points total by more than its
 * own rounding, which means the class weighs categories. */
export function weighsCategories(days: TrendDay[], genesisPercent: number | null): boolean {
  const last = lastGrade(days);
  return last != null && genesisPercent != null && Math.abs(last - genesisPercent) > 1;
}
