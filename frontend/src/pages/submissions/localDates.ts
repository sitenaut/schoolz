// A submission item's dates are local wall-clock strings ("2026-10-14" or
// "2026-10-14T17:00:00") exactly as read off the flyer. They are formatted
// and edited as strings here on purpose: routing them through Date would
// re-interpret them in the reviewer's own timezone.

export type DateParts = { date: string; time: string; endDate: string; endTime: string };

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const datePart = (local: string | null) => (local ? local.slice(0, 10) : "");
const timePart = (local: string | null) => (local && local.length > 10 ? local.slice(11, 16) : "");

export function splitLocal(start: string | null, end: string | null): DateParts {
  const date = datePart(start);
  const endDate = datePart(end);
  return { date, time: timePart(start), endDate: endDate === date ? "" : endDate, endTime: timePart(end) };
}

const join = (date: string, time: string) => (time ? `${date}T${time}:00` : date);

/** "" for either value means "no date" / "no end", which is what the API
 * takes to clear the field. */
export function joinLocal(parts: DateParts): { start_local: string; end_local: string } {
  if (!parts.date) return { start_local: "", end_local: "" };
  const hasEnd = Boolean(parts.endDate || parts.endTime);
  return {
    start_local: join(parts.date, parts.time),
    end_local: hasEnd ? join(parts.endDate || parts.date, parts.endTime) : "",
  };
}

function day(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return `${WEEKDAYS[new Date(y, m - 1, d).getDay()]} ${MONTHS[m - 1]} ${d}`;
}

function clock(time: string): { text: string; half: string } {
  const [h, m] = time.split(":").map(Number);
  const hour = h % 12 || 12;
  return { text: m ? `${hour}:${String(m).padStart(2, "0")}` : String(hour), half: h < 12 ? "am" : "pm" };
}

/** "Wed Oct 14 · 5–10 pm" */
export function formatWhen(start: string | null, end: string | null): string {
  if (!start) return "No date";
  const p = splitLocal(start, end);
  let out = day(p.date);
  if (p.time) {
    const a = clock(p.time);
    if (p.endTime && !p.endDate) {
      const b = clock(p.endTime);
      out += ` · ${a.text}${a.half === b.half ? "" : ` ${a.half}`}–${b.text} ${b.half}`;
    } else {
      out += ` · ${a.text} ${a.half}`;
    }
  }
  if (p.endDate) {
    out += ` – ${day(p.endDate)}`;
    if (p.endTime) {
      const b = clock(p.endTime);
      out += ` · ${b.text} ${b.half}`;
    }
  }
  return out;
}
