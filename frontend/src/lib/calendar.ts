export type CalendarableItem = {
  title: string;
  description?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  is_all_day: boolean;
};

function toAllDayStamp(iso: string): string {
  return iso.slice(0, 10).replace(/-/g, "");
}

function toTimedStamp(iso: string): string {
  return new Date(iso).toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
}

/** No OAuth needed - opens Google's own "quick add" page pre-filled. */
export function googleCalendarQuickAddUrl(item: CalendarableItem): string | null {
  if (!item.start_date) return null;

  let start: string;
  let end: string;
  if (item.is_all_day) {
    start = toAllDayStamp(item.start_date);
    const endSource = item.end_date
      ? new Date(item.end_date)
      : new Date(new Date(item.start_date).getTime() + 24 * 60 * 60 * 1000);
    end = toAllDayStamp(endSource.toISOString());
  } else {
    start = toTimedStamp(item.start_date);
    end = toTimedStamp(item.end_date || item.start_date);
  }

  const params = new URLSearchParams({ action: "TEMPLATE", text: item.title, dates: `${start}/${end}` });
  if (item.description) params.set("details", item.description);
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

export function formatDate(iso: string, allDay: boolean): string {
  const d = new Date(iso);
  return allDay
    ? d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
    : d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** School-local calendar date (YYYY-MM-DD) for an ISO timestamp - every
 * date in the app is a Cherry Hill date, whatever timezone the browser is in. */
export function localDateKey(iso: string): string {
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Today's date in school-local time. */
export function todayKey(): string {
  return localDateKey(new Date().toISOString());
}

/** Every school-local date key (YYYY-MM-DD) a multi-day item covers, not
 * just its start_date - a calendar grid/day-lookup keyed on start_date
 * alone silently drops every day but the first of a multi-day item (real
 * case: "SCHOOLS CLOSED - NJEA Convention" spanning Nov 5-6 only showed as
 * closed on Nov 5). All-day items store end_date as the ICS convention's
 * exclusive day-after-the-last-day (confirmed real: start Nov 5, end Nov
 * 7, covering Nov 5-6); a timed item's end_date, if it lands on a later
 * calendar day at all, is treated as inclusive of that day instead. */
export function itemDateKeys(item: { start_date?: string | null; end_date?: string | null; is_all_day?: boolean }): string[] {
  if (!item.start_date) return [];
  const startKey = localDateKey(item.start_date);
  if (!item.end_date) return [startKey];
  let endKey = localDateKey(item.end_date);
  if (item.is_all_day) {
    const endDate = new Date(endKey + "T12:00:00Z");
    endDate.setUTCDate(endDate.getUTCDate() - 1);
    endKey = endDate.toISOString().slice(0, 10);
  }
  if (endKey <= startKey) return [startKey];
  const keys: string[] = [];
  const cursor = new Date(startKey + "T12:00:00Z");
  const end = new Date(endKey + "T12:00:00Z");
  while (cursor <= end) {
    keys.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return keys;
}

/** Short "Wed 9" / "Sep 25" label - weekday form inside the next 6 days, month form after. */
export function shortDay(iso: string, relativeTo = todayKey()): string {
  const key = localDateKey(iso);
  const d = new Date(key + "T12:00:00Z");
  const diff = (Date.parse(key) - Date.parse(relativeTo)) / 86_400_000;
  if (diff >= 0 && diff < 7) return `${d.toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" })} ${d.getUTCDate()}`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

export function monthDay(key: string): { month: string; day: string } {
  const d = new Date(key.slice(0, 10) + "T12:00:00Z");
  return { month: d.toLocaleDateString(undefined, { month: "short", timeZone: "UTC" }), day: String(d.getUTCDate()) };
}

export function timeOfDay(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
}

export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}
