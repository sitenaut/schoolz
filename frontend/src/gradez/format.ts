// Wording shared by Gradez's tabs. Display only: nothing here decides what
// counts as missing, late or graded - the API does.
import { dueLabel } from "./courses";
import type { Announcement, GradeEntry, LateCredit, LatePolicy } from "./types";

/** Two letters for a class's tile: "World History" -> "WH", "Geometry" -> "Ge",
 * "English 10" -> "En" (a number says less than the name it follows). */
export function initials(name: string): string {
  const all = name.split(/[^A-Za-z0-9]+/).filter(Boolean);
  const words = all.some((w) => /[A-Za-z]/.test(w)) ? all.filter((w) => /[A-Za-z]/.test(w)) : all;
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 1).toUpperCase() + words[0].slice(1, 2).toLowerCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

export function mailtoHref(emails: string[], subject?: string): string | null {
  if (!emails.length) return null;
  return `mailto:${emails.join(",")}${subject ? `?subject=${encodeURIComponent(subject)}` : ""}`;
}

/** "MP2" -> "Marking period 2". Any other label is shown as the school wrote it. */
export function markingPeriodName(label: string): string {
  const n = /^MP(\d)$/i.exec(label)?.[1];
  return n ? `Marking period ${n}` : label;
}

/** The class a Genesis row belongs to, as /todo and /progress key it. */
export function genesisKey(row: { course_code: string; course_section: string }): string {
  return row.course_section ? `${row.course_code}-${row.course_section}` : row.course_code;
}

// A score or a mark (Missing, Exempt); Genesis lists the rest as "No Grade".
export function isGraded(e: GradeEntry): boolean {
  return e.score_earned != null || e.percent != null || e.status != null;
}

function trimNumber(n: number): string {
  return String(Math.round(n * 100) / 100);
}

/** "41 / 50", a mark Genesis put instead of a score, or null when ungraded. */
export function scoreText(e: GradeEntry): string | null {
  if (e.status) return e.status;
  if (e.score_earned != null && e.score_possible != null) return `${trimNumber(e.score_earned)} / ${trimNumber(e.score_possible)}`;
  if (e.percent != null) return `${Math.round(e.percent)}%`;
  return null;
}

export function percentText(percent: number): string {
  return `${Math.round(percent)}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Genesis prints "Mon 11/9" with no year: "Mon, Nov 9". */
export function genesisDate(weekdayDate: string): string {
  const match = /^(\S+)\s+(\d{1,2})\/(\d{1,2})$/.exec(weekdayDate.trim());
  if (!match) return weekdayDate;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${match[1]}, ${month} ${Number(match[3])}` : weekdayDate;
}

/** Newest first for Genesis's yearless dates; a school year runs July to June. */
export function genesisOrder(e: GradeEntry): number {
  const [month, day] = (e.weekday_date.split(" ").pop() ?? "").split("/").map(Number);
  return ((month < 7 ? month + 12 : month) || 0) * 100 + (day || 0);
}

/** "7:30 AM" -> "7:30": a school day needs no AM or PM. */
export function clockLabel(label: string | null): string {
  return (label ?? "").replace(/\s*[AP]M$/i, "");
}

/** Minutes since midnight for "7:30 AM" or "13:05"; null when unreadable. */
export function clockMinutes(label: string | null): number | null {
  const match = /^(\d{1,2}):(\d{2})\s*([AP]M)?$/i.exec((label ?? "").trim());
  if (!match) return null;
  let hours = Number(match[1]);
  const half = match[3]?.toUpperCase();
  if (half === "PM" && hours < 12) hours += 12;
  if (half === "AM" && hours === 12) hours = 0;
  return hours * 60 + Number(match[2]);
}

/** "Today, 8:32 AM" / "Yesterday, 8:32 AM" / "Dec 4, 8:32 AM" for a timestamp. */
export function whenLabel(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "Not yet";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "Not yet";
  const time = at.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const dayStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((dayStart(now) - dayStart(at)) / 86400000);
  if (days === 0) return `Today, ${time}`;
  if (days === 1) return `Yesterday, ${time}`;
  return `${at.toLocaleDateString(undefined, { month: "short", day: "numeric" })}, ${time}`;
}

/** "2 h ago" -> "2 hours ago": the About this data sheet has room for words. */
export function agoWords(ago: string): string {
  return ago.replace(/^(\d+) min ago$/, "$1 minutes ago").replace(/^1 h ago$/, "1 hour ago").replace(/^(\d+) h ago$/, "$1 hours ago");
}

/** "Sam's" / "Chris's". */
export function possessive(name: string): string {
  return `${name}'s`;
}

export function plural(n: number, one: string, many: string = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Classroom hands out links relative to its own site. */
export function classroomLink(link: string | null): string | null {
  if (!link) return null;
  return /^https?:\/\//.test(link) ? link : `https://classroom.google.com${link.startsWith("/") ? "" : "/"}${link}`;
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** "2026-12-08" -> "Tuesday". */
export function weekdayName(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return WEEKDAYS[new Date(y, m - 1, d).getDay()] ?? iso;
}

/** When a teacher posted: "Today", "Yesterday", the weekday within a week,
 * then "Dec 4". Classroom's own wording when the date couldn't be read. */
export function postedLabel(a: Pick<Announcement, "posted_date" | "posted_raw">, todayIso: string): string | null {
  if (!a.posted_date) return a.posted_raw;
  const [y, m, d] = a.posted_date.split("-").map(Number);
  const [ty, tm, td] = todayIso.split("-").map(Number);
  if (!y || !ty) return a.posted_raw ?? a.posted_date;
  const date = new Date(y, m - 1, d);
  const days = Math.round((new Date(ty, tm - 1, td).getTime() - date.getTime()) / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days > 1 && days < 7) return WEEKDAYS[date.getDay()];
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function days(n: number | null): string {
  return n == null ? "a few days" : plural(n, "day");
}

// The rule itself, before its cutoff. Days are calendar days, as the API counts them.
function policyRule(p: LatePolicy): string {
  switch (p.shape) {
    case "full_credit":
      return "Late work is accepted for full credit.";
    case "flat":
      return `${p.penalty_pct ?? "Some"}% off late work, however late it is.`;
    case "daily_decay":
      return `${p.penalty_per_day ?? "Some"}% off for each day late.${p.floor_pct != null ? ` Never below ${p.floor_pct}%.` : ""}`;
    case "window":
      return `Full credit for ${days(p.window_days)} after the due date. Not accepted after that.`;
    case "tiered": {
      const steps = (p.steps ?? []).map((s) => `${s.credit_pct}% within ${plural(s.days, "day")}`);
      return steps.length ? `Worth ${steps.join(", ")}. Not accepted after that.` : "Worth less the later it is.";
    }
    case "not_accepted":
      return "Late work is not accepted.";
    default:
      return "A late-work rule is on file.";
  }
}

/** A saved late-work rule as sentences a parent can check against the syllabus. */
export function policySentence(p: LatePolicy, todayIso: string): string {
  const rule = policyRule(p);
  if (p.shape === "not_accepted" || !p.accepted_until) return rule;
  if (p.accepted_until === "marking_period_end") return `${rule} Accepted until the marking period ends.`;
  return `${rule} Accepted until ${dueLabel(p.accepted_until, todayIso)}.`;
}

/** What one late item is still worth, for a class page's missing list. */
export function lateLine(credit: LateCredit | null, dueDate: string | null, todayIso: string): string {
  const due = dueDate ? `Was due ${dueLabel(dueDate, todayIso)}.` : "Past due.";
  if (!credit) return `${due} No late-work rule on file for this class.`;
  const until = credit.closes_on ? ` until ${dueLabel(credit.closes_on, todayIso)}` : "";
  if (!credit.accepted) return credit.closes_on ? `Closed ${dueLabel(credit.closes_on, todayIso)}. Kept off To do.` : "Too late for credit. Kept off To do.";
  const worth = credit.credit_pct == null ? "Still accepted" : credit.credit_pct >= 100 ? "Worth full credit" : `Worth up to ${Math.round(credit.credit_pct)}%`;
  return `${credit.by_exception ? "A teacher said they'd still take this. " : `${due} `}${worth}${until}.`;
}
