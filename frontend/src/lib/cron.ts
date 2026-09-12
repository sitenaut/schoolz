const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const DAY_ALIASES: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };

export const CRON_PRESETS: { label: string; expr: string }[] = [
  { label: "Every 10 minutes", expr: "*/10 * * * *" },
  { label: "Every hour", expr: "0 * * * *" },
  { label: "Every 6 hours", expr: "0 */6 * * *" },
  { label: "Every 12 hours", expr: "0 */12 * * *" },
  { label: "Daily at 6:00 AM", expr: "0 6 * * *" },
  { label: "Daily at 7:00 AM", expr: "0 7 * * *" },
  { label: "Daily at 8:00 AM", expr: "0 8 * * *" },
  { label: "Weekdays at 7:00 AM", expr: "0 7 * * 1-5" },
  { label: "Weekly, Monday 8:00 AM", expr: "0 8 * * 1" },
  { label: "Weekly, Sunday 6:00 PM", expr: "0 18 * * 0" },
];

function clock(h: number, m: number): string {
  const suffix = h >= 12 ? "PM" : "AM";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}:${String(m).padStart(2, "0")} ${suffix}`;
}

function dayName(token: string): string | null {
  const n = /^\d$/.test(token) ? Number(token) : DAY_ALIASES[token.toLowerCase()];
  return n === undefined || n < 0 || n > 6 ? null : DAYS[n];
}

/** Plain-English gloss for the handful of cron shapes this app actually
 * uses (fixed times, every-N-hours/minutes, weekday lists). Anything
 * fancier falls back to the raw expression - it's a label, not a parser. */
export function describeCron(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, dom, mon, dow] = parts;
  const isNum = (s: string) => /^\d+$/.test(s);

  if (dom === "*" && mon === "*") {
    // Interval shapes
    if (isNum(min) && /^\*\/\d+$/.test(hour) && dow === "*") {
      return `Every ${hour.slice(2)} hours at :${min.padStart(2, "0")}`;
    }
    if (/^\*\/\d+$/.test(min) && hour === "*" && dow === "*") {
      return `Every ${min.slice(2)} minutes`;
    }
    if (isNum(min) && hour === "*" && dow === "*") {
      return `Every hour at :${min.padStart(2, "0")}`;
    }
    // Fixed time, possibly on specific days
    if (isNum(min) && isNum(hour)) {
      const time = clock(Number(hour), Number(min));
      if (dow === "*") return `Daily at ${time}`;
      if (dow === "1-5") return `Weekdays at ${time}`;
      if (dow === "0,6" || dow === "6,0") return `Weekends at ${time}`;
      if (dow.includes(",")) {
        const names = dow.split(",").map(dayName);
        if (names.every(Boolean)) return `${names.map((n) => n!.slice(0, 3)).join(", ")} at ${time}`;
      }
      const single = dayName(dow);
      if (single) return `Weekly on ${single} at ${time}`;
    }
  }
  if (isNum(min) && isNum(hour) && isNum(dom) && mon === "*" && dow === "*") {
    const d = Number(dom);
    const ord = d === 1 ? "1st" : d === 2 ? "2nd" : d === 3 ? "3rd" : `${d}th`;
    return `Monthly on the ${ord} at ${clock(Number(hour), Number(min))}`;
  }
  return expr;
}
