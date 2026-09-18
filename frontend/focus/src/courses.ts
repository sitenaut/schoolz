// Display-layer helpers for course names and tile colours.

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

export function tileColor(key: string): string {
  let hash = 0;
  for (let i = 0; i < key.length; i++) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return TILE_COLORS[hash % TILE_COLORS.length];
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
