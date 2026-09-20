// Display-layer helpers for course names and tile colours.
import type { TodoItem } from "./types";

// Used by sortMissingByRecency - how many days from a closing late-credit
// window still counts as urgent enough to jump the queue ahead of newer
// backlog (see the function's own docstring for the reasoning).
const CLOSING_SOON_DAYS = 2;

/** Most-recently-missed first - the backend hands these oldest-first, but
 * for anything meant to prompt action that's backwards: the thing missed
 * two days ago is the one a teacher is most likely to still accept and the
 * one a kid can still half-remember; the one from six weeks ago is
 * neither. The one exception is a closing credit window, which has the
 * same "acting now changes the outcome" property near-term due-soon work
 * has, so it jumps the queue - soonest to close first.
 *
 * Shared by FocusTab (filling Up Next / ordering Needs Attention) and
 * CourseSheet (a single class's own Missing section, "the Focus page
 * filtered to just this class") so the two apply exactly one rule rather
 * than risking two different orderings for what's supposed to be the same
 * thing, scoped differently - the same class of bug the color/name
 * mismatches already were. */
export function sortMissingByRecency(items: TodoItem[]): TodoItem[] {
  const closingSoon = (i: TodoItem) =>
    i.late_credit?.days_left != null && i.late_credit.days_left <= CLOSING_SOON_DAYS;
  return [...items].sort((a, b) => {
    const [ac, bc] = [closingSoon(a), closingSoon(b)];
    if (ac !== bc) return ac ? -1 : 1;
    if (ac && bc) return (a.late_credit!.days_left ?? 0) - (b.late_credit!.days_left ?? 0);
    return (a.due_date ?? "") < (b.due_date ?? "") ? 1 : -1;
  });
}

/** Classroom course names carry the district's own bookkeeping in them -
 * "GEOM A Per A 2026-27 210-1", "F: CHEM-1A 331-10", "PD S1 PHILOSOPHY:
 * ... 2026-27 570-1". All of it is real and load-bearing elsewhere (the
 * trailing NNN-N is the cross-source link to Genesis), but none of it
 * belongs on a tile a 15-year-old reads at 7:40am.
 *
 * This strips for DISPLAY only and never for matching - nothing downstream
 * keys off the result. */
export function shortCourseName(name: string): string {
  let out = name;
  // Any digit-dash-digit run, INCLUDING its surrounding brackets. The
  // brackets have to go in the same pass: matching the digits alone turns
  // "ENG 2A Block B (26-27) 121-1" into "ENG 2A ( )", because "26-27" is
  // eaten from inside the parens before any bracket rule can see it.
  // Course codes ("121-1"), academic years ("2026-27") and short year
  // ranges ("26-27") are all dropped here - unlike the backend, which must
  // tell them apart, this is display-only and drops all three.
  out = out.replace(/\(?\s*\b\d{2,4}[A-Z]?-\d{1,2}\b\s*\)?/g, " ");
  out = out.replace(/\(\s*S[1-4]\s*\)/gi, " "); // "(S1)"
  out = out.replace(/\bPer(?:iod)?\.?\s+[A-Z]\b/g, " "); // "Per A", "Period G"
  out = out.replace(/\b(?:Block|Pd)\.?\s+[A-Z]\b/g, " "); // "Block B", "Pd E"
  out = out.replace(/\b[A-Z]\s+Block\b/g, " "); // "H Block", "D Block"
  out = out.replace(/^\s*(?:F|PD)\s*S?\d?\s*:\s*/i, ""); // "F: "
  out = out.replace(/^\s*PD\s+S\d\s+/i, ""); // "PD S1 "
  out = out.replace(/\b(?:FY|S[1-4]|Q[1-4]|MP[1-4])\b/g, " "); // term labels
  out = out.replace(/\(\s*\)/g, " "); // anything the rules above hollowed out
  out = out.replace(/[,\s]+/g, " ").replace(/\s*:\s*$/, "").trim();
  return out || name;
}

/** The name to actually show for a class: a student's own rename (lib/
 * courseNames.ts, keyed by course_key - same identity the color override
 * uses) if one is set, otherwise shortCourseName's auto-stripped version.
 * One function so every screen that shows a class name resolves it the
 * same way - the color mismatch bug (two screens hashing two different
 * strings for what was supposed to be one color) is exactly the failure
 * mode a second, separately-applied override would risk repeating. */
export function displayCourseName(rawName: string, customName?: string): string {
  return customName?.trim() || shortCourseName(rawName);
}

// Deliberately a fixed palette rather than a generated hue: the mockup's
// tiles read as a set, and generated hues drift into muddy or clashing
// neighbours. Index is a stable hash of the course key so a class keeps
// its colour between sessions and across devices.
const TILE_COLORS = [
  "tile-blue",
  "tile-green",
  "tile-red",
  "tile-orange",
  "tile-yellow",
  "tile-sky",
  "tile-violet",
  "tile-slate",
  "tile-purple",
  "tile-emerald",
];

// The same ten swatches as TILE_COLORS, as real hex values rather than CSS
// custom-property names - needed to paint the color-picker's own preset
// swatches (a swatch button has to show its actual color before anyone
// taps it, not just carry a class name). Must stay in sync with the
// --tile-* declarations in styles.css :root; there's no single source of
// truth to derive one from the other without a build step, so a mismatch
// here would only ever show up as a picker swatch not matching what
// tapping it produces.
export const PALETTE_HEXES = [
  "#5b9bd5",
  "#57c78a",
  "#ef5f5f",
  "#f2a145",
  "#f5d34e",
  "#63bde8",
  "#b08ce0",
  "#93a2b3",
  "#7d5bc6",
  "#3faa6d",
];

// Shared between tileColorClass and defaultPaletteHex, which MUST agree on
// which of the ten slots a given key lands in - TILE_COLORS and
// PALETTE_HEXES are the same set in the same order, so one index picks the
// matching entry from either.
function paletteIndex(key: string): number {
  let hash = 0;
  for (let i = 0; i < key.length; i++) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return hash % TILE_COLORS.length;
}

function tileColorClass(key: string): string {
  return TILE_COLORS[paletteIndex(key)];
}

export function tileColor(key: string): string {
  return tileColorClass(key);
}

/** The hex a class would get with no custom override - what the color
 * picker highlights as "current" when nothing's been picked yet, so the
 * picker never shows every swatch as unselected while a color is visibly
 * already applied. */
export function defaultPaletteHex(courseKey: string): string {
  return PALETTE_HEXES[paletteIndex(courseKey)];
}

/** The class-key-first color resolution used everywhere a class needs a
 * color: Focus's task chips, Subjects tiles, the course sheet. A custom
 * pick (from lib/courseColors.ts, keyed by the same course_key) wins as an
 * inline CSS-custom-property override; otherwise the deterministic
 * palette class applies. Centralising this is what keeps Focus and
 * Subjects from picking two different colors for the same class - they
 * disagreed once already, from hashing two different strings
 * (course_name vs course_key) for what was supposed to be one color. */
export function courseColorProps(courseKey: string, customHex?: string): { className: string; style?: { [key: string]: string } } {
  if (customHex) return { className: "", style: { "--tile": customHex, "--chip": customHex } };
  return { className: tileColorClass(courseKey) };
}

/** "Today" / "Tomorrow" / "Mon 14" for an ISO date, in local terms.
 *
 * Built from the date parts rather than `new Date(iso)`, which parses a
 * bare "2026-09-16" as UTC midnight and then renders it in local time -
 * the same off-by-one-day trap the backend's _parse_date and the main
 * app's localDateKey exist to avoid. */
export function dueLabel(iso: string | null, todayIso: string): string | null {
  if (!iso) return null;
  if (iso === todayIso) return "Today";
  const [y, m, d] = iso.split("-").map(Number);
  const [ty, tm, td] = todayIso.split("-").map(Number);
  if (!y || !ty) return iso;
  const date = new Date(y, m - 1, d);
  const today = new Date(ty, tm - 1, td);
  const days = Math.round((date.getTime() - today.getTime()) / 86400000);
  if (days === 1) return "Tomorrow";
  if (days === -1) return "Yesterday";
  const weekday = date.toLocaleDateString(undefined, { weekday: "short" });
  if (days > 1 && days < 7) return `${weekday} ${d}`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function fromIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function toIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export type Horizon = { today: string; next: string; nextLabel: string };

/** The dashboard's whole world: today and the next school day.
 *
 * "Tomorrow" is the wrong horizon on a Friday - nothing is due Saturday, so
 * a literal tomorrow shows an empty dashboard on the one evening when
 * Monday's work is exactly what should be visible. The horizon skips the
 * weekend and is labelled by weekday when it does, so "Monday" reads as
 * the honest boundary rather than a fake "Tomorrow". */
export function horizon(todayIso: string): Horizon {
  const today = fromIso(todayIso);
  const next = new Date(today);
  next.setDate(next.getDate() + 1);
  while (next.getDay() === 0 || next.getDay() === 6) next.setDate(next.getDate() + 1);
  const isLiteralTomorrow = Math.round((next.getTime() - today.getTime()) / 86400000) === 1;
  return { today: todayIso, next: toIso(next), nextLabel: isLiteralTomorrow ? "Tomorrow" : WEEKDAYS[next.getDay()] };
}

export function daysFromToday(iso: string, todayIso: string): number {
  return Math.round((fromIso(iso).getTime() - fromIso(todayIso).getTime()) / 86400000);
}

export function localTodayIso(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
