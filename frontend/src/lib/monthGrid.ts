/** Month/year calendar grid helpers shared by /calendar and /local. */

export const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export const WEEKDAY_INITIALS = ["S", "M", "T", "W", "T", "F", "S"];
export const MONTH_NAMES = Array.from({ length: 12 }, (_, m) => new Date(2000, m, 1).toLocaleDateString(undefined, { month: "short" }));

export function dateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function endOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59);
}

/** Calendar cells for one month (leading blanks + every day), used for
 * both the full month grid and each small grid in year view. */
export function monthCells(year: number, month: number): (Date | null)[] {
  const leadingBlanks = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (Date | null)[] = [...Array(leadingBlanks).fill(null)];
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  return cells;
}
