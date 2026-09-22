import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { RIBBON_CHANGE_EVENT, useMySchools } from "../lib/mySchools";
import { apiFetch } from "../api";
import { ItemRow } from "../components/today";
import { SeoHead } from "../components/SeoHead";
import { usePrerenderReady } from "../lib/prerenderReady";
import { IconChevronLeft, IconChevronRight } from "../components/icons";
import { CLOSED_RE, HALF_DAY_RE, expandItemRows, isNoisyDistrictItem, isRotationItem } from "../lib/districtItems";
import { trackEvent, trackMeasurement } from "../lib/track";
import { itemDateKeys } from "../lib/calendar";
import type { School, SchoolContentItem } from "../types";
import styles from "./CalendarPage.module.css";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY_INITIALS = ["S", "M", "T", "W", "T", "F", "S"];
const MONTH_NAMES = Array.from({ length: 12 }, (_, m) => new Date(2000, m, 1).toLocaleDateString(undefined, { month: "short" }));
type ViewMode = "month" | "year";

function dateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function endOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59);
}

/** Calendar cells for one month (leading blanks + every day), used for
 * both the full month grid and each small grid in year view. */
function monthCells(year: number, month: number): (Date | null)[] {
  const leadingBlanks = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (Date | null)[] = [...Array(leadingBlanks).fill(null)];
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  return cells;
}

const TODAY_KEY = dateKey(new Date());

export function CalendarPage() {
  const { mySchools, activeSchools, colorFor, loading, excludeDistrict, setExcludeDistrict } = useMySchools();
  const [params, setParams] = useSearchParams();
  const deepSchool = params.get("school");
  // A "this week" tap (school page) deep-links a specific day, and an
  // event pill within it also carries which item to land on/highlight.
  const deepDate = params.get("date");
  const deepEvent = params.get("event");
  // Which schools' dates are shown - the same top-ribbon "my schools"
  // selection every other page uses, no separate picker here anymore. A
  // school page's "see all dates" deep link narrows to just that one
  // school instead, same as before.
  //
  // That narrowing is temporary and visible: a bar says which school it is,
  // and tapping it or any ribbon chip drops ?school= so the ribbon governs
  // again. It used to override the ribbon silently, and survive a reload, so
  // the ribbon looked broken on this page.
  const schoolSlugs = useMemo(() => (deepSchool ? [deepSchool] : activeSchools.map((s) => s.slug)), [deepSchool, activeSchools]);
  const clearSchoolFilter = () => {
    setScrollToToday(true);
    setParams(
      (cur) => {
        const next = new URLSearchParams(cur);
        next.delete("school");
        next.delete("date");
        next.delete("event");
        return next;
      },
      { replace: true },
    );
  };
  useEffect(() => {
    if (!deepSchool) return;
    window.addEventListener(RIBBON_CHANGE_EVENT, clearSchoolFilter);
    return () => window.removeEventListener(RIBBON_CHANGE_EVENT, clearSchoolFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepSchool]);
  const [fetchedDeepSchool, setFetchedDeepSchool] = useState<School | null>(null);
  const deepSchoolObj = deepSchool ? (mySchools.find((s) => s.slug === deepSchool) ?? (fetchedDeepSchool?.slug === deepSchool ? fetchedDeepSchool : null)) : null;
  useEffect(() => {
    if (!deepSchool || loading || mySchools.some((s) => s.slug === deepSchool)) return;
    apiFetch(`/schools/${deepSchool}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setFetchedDeepSchool);
  }, [deepSchool, loading, mySchools]);
  // Rows are labeled per school the page is scoped to - the linked school,
  // not the ribbon's, or its type-restricted district items get dropped.
  const scopedSchools = useMemo(() => (deepSchoolObj ? [deepSchoolObj] : activeSchools), [deepSchoolObj, activeSchools]);
  const schoolIdsKey = schoolSlugs.join(",");
  const [viewMode, setViewMode] = useState<ViewMode>("month");
  const [viewDate, setViewDate] = useState(() => startOfMonth(deepDate ? new Date(deepDate + "T12:00:00Z") : new Date()));
  const [items, setItems] = useState<SchoolContentItem[]>([]);
  // Lands filtered to today - both a default and a live filter, cleared
  // by tapping today's cell again, any other cell, or "Show month". A
  // deep-linked date (from a school page's "this week" strip) wins over
  // today the same way an explicit school id already wins over the ribbon.
  // A school's "All dates" link (no date) lands on that school's whole month
  // instead, scrolled to today - same as "Show month".
  const [selectedDay, setSelectedDay] = useState<string | null>(deepDate ?? (deepSchool ? null : TODAY_KEY));
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const isSearching = searchTerm.trim().length > 0;
  // On by default - a visitor who doesn't know this toggle exists should
  // still see rotation days; the checkbox lets someone who doesn't care
  // hide them instead.
  const [showDayRotation, setShowDayRotation] = useState(true);
  const [dataReady, setDataReady] = useState(false);
  // Which school selection `items` was fetched for - scrolling to today has
  // to wait for the list that matches the current selection.
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  usePrerenderReady(dataReady);

  const readyStart = useRef(performance.now());
  const readyReported = useRef(false);

  // Debounced so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setSearchTerm(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Re-syncs the view when a second deep link (a different day or event
  // pill) is followed while this page is already mounted - the state
  // above only seeds the initial render, and React Router reuses this
  // component across such navigations instead of remounting it.
  useEffect(() => {
    if (!deepDate) return;
    setViewDate(startOfMonth(new Date(deepDate + "T12:00:00Z")));
    setSelectedDay(deepDate);
    setViewMode("month");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepDate]);

  useEffect(() => {
    if (loading) return;
    const q = new URLSearchParams();
    if (isSearching) {
      // Search looks across every upcoming (and recent) event, not just
      // whatever month or year happens to be on screen - the backend's
      // own text search does the matching, server-side, unbounded.
      q.set("q", searchTerm.trim());
      q.set("start", new Date(Date.now() - 7 * 86400000).toISOString());
    } else if (viewMode === "year") {
      q.set("start", new Date(viewDate.getFullYear(), 0, 1).toISOString());
      q.set("end", new Date(viewDate.getFullYear(), 11, 31, 23, 59, 59).toISOString());
    } else {
      q.set("start", startOfMonth(viewDate).toISOString());
      q.set("end", endOfMonth(viewDate).toISOString());
    }
    if (schoolSlugs.length) q.set("school_ids", schoolIdsKey);
    if (category) q.set("category", category);
    const searchedTerm = isSearching ? searchTerm.trim() : null;
    apiFetch(`/calendar?${q.toString()}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: SchoolContentItem[]) => {
        setItems(data);
        setDataReady(true);
        setLoadedKey(schoolIdsKey);
        if (!readyReported.current) {
          readyReported.current = true;
          trackMeasurement("calendar_ready", performance.now() - readyStart.current, { mode: isSearching ? "search" : viewMode });
        }
        // Never the query text itself, per privacy guardrails - just its shape.
        if (searchedTerm) {
          trackEvent("calendar_search", { result_count: data.length, query_length: searchedTerm.length });
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewDate, viewMode, schoolIdsKey, category, loading, isSearching, searchTerm]);

  const colorForName = (name: string | null) => {
    const s = scopedSchools.find((m) => (m.short_name || m.name) === name);
    return s ? colorFor(s.id) : "var(--district)";
  };
  const showEmptySelectionNote = activeSchools.length === 0;

  // Exclude-district and day-rotation both narrow what's visible before
  // anything else touches the data - the month grid's dots/status colors
  // and the list below need to agree, or a dot with nothing behind it
  // (once tapped) reads as a bug.
  const visibleItems = useMemo(
    () =>
      items.filter((i) => {
        if (isRotationItem(i.title) && !showDayRotation) return false;
        if (excludeDistrict && isNoisyDistrictItem(i)) return false;
        return true;
      }),
    [items, excludeDistrict, showDayRotation],
  );

  const eventsByDay = useMemo(() => {
    const map = new Map<string, SchoolContentItem[]>();
    for (const item of visibleItems) {
      for (const key of itemDateKeys(item)) {
        map.set(key, [...(map.get(key) ?? []), item]);
      }
    }
    return map;
  }, [visibleItems]);

  const grid = useMemo(() => monthCells(viewDate.getFullYear(), viewDate.getMonth()), [viewDate]);

  const changeMonth = (delta: number) => {
    setViewDate((d) => new Date(d.getFullYear(), d.getMonth() + delta, 1));
    // A day filter tied to a month that's no longer in view is confusing -
    // land on the new month showing everything in it.
    setSelectedDay(null);
  };

  const changeYear = (delta: number) => {
    setViewDate((d) => new Date(d.getFullYear() + delta, d.getMonth(), 1));
    setSelectedDay(null);
  };

  const tapDay = (key: string, cellDate: Date) => {
    // Browsing a specific day and searching are two different intents -
    // picking a day drops out of search mode back to the calendar.
    if (isSearching) setSearch("");
    // Picking a day from the year overview jumps into that month so the
    // filtered list below shows the same detail the month view would.
    if (viewMode === "year") {
      setViewDate(startOfMonth(cellDate));
      setViewMode("month");
      setSelectedDay(key);
      return;
    }
    setSelectedDay((cur) => (cur === key ? null : key));
  };

  const filteredItems = useMemo(() => {
    const list = !isSearching && selectedDay && viewMode === "month" ? visibleItems.filter((i) => itemDateKeys(i).includes(selectedDay)) : visibleItems;
    return [...list].sort((a, b) => ((a.start_date ?? "") < (b.start_date ?? "") ? -1 : 1));
  }, [visibleItems, selectedDay, isSearching, viewMode]);

  // One item can render as several rows - a district item restricted to
  // specific school types (a type-only half day, or - with the rotation
  // filter on - a "Day N" marker) expands into one labeled row per
  // currently-active school of a matching type, e.g. "Day 3 [Bret Harte]"
  // and "Day 2 [Cherry Hill East]" side by side rather than one row
  // labeled just "Elementary" or "High school".
  const rows = useMemo(() => filteredItems.flatMap((i) => expandItemRows(i, scopedSchools)), [filteredItems, scopedSchools]);

  // Land on the specific event a "this week" pill pointed at, not just its
  // day - the list can still hold several items for that date.
  useEffect(() => {
    if (!deepEvent) return;
    const el = document.getElementById(`event-${deepEvent}`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [deepEvent, rows]);

  // "Show month" lands on today, like the lunch calendar: the whole month is
  // listed, scrolled to today's first entry (or the next day that has one).
  // Viewing another month, there's no "today" in the list, so it stays put.
  const [scrollToToday, setScrollToToday] = useState(Boolean(deepSchool && !deepDate));
  const showMonth = () => {
    setSelectedDay(null);
    setScrollToToday(true);
  };
  useEffect(() => {
    if (!scrollToToday || selectedDay || loadedKey !== schoolIdsKey) return;
    setScrollToToday(false);
    const target = rows.find(({ item }) => itemDateKeys(item).some((k) => k >= TODAY_KEY));
    if (!target || !TODAY_KEY.startsWith(dateKey(viewDate).slice(0, 7))) return;
    document.getElementById(`event-${target.item.id}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [scrollToToday, selectedDay, rows, viewDate, loadedKey, schoolIdsKey]);

  const selectedLabel = selectedDay
    ? new Date(selectedDay + "T12:00:00Z").toLocaleDateString(undefined, {
        weekday: "long",
        month: "long",
        day: "numeric",
        ...(selectedDay.slice(0, 4) !== TODAY_KEY.slice(0, 4) ? { year: "numeric" } : {}),
      })
    : null;

  // "No school" status for one day, from whatever landed on it - closed
  // (holiday/in-service/conference) beats half day beats an ordinary
  // weekend, same precedence the Today card uses. A closure landing on a
  // weekend still shows as "closed", not "weekend" - the more specific
  // fact wins.
  const dayStatus = (key: string, dow: number): "closed" | "half" | "weekend" | null => {
    const dayEvents = eventsByDay.get(key);
    if (dayEvents?.some((e) => CLOSED_RE.test(e.title))) return "closed";
    if (dayEvents?.some((e) => HALF_DAY_RE.test(e.title))) return "half";
    if (dow === 0 || dow === 6) return "weekend";
    return null;
  };

  const dayButtonClasses = (d: Date, mini = false) => {
    const key = dateKey(d);
    const hasEvents = eventsByDay.has(key);
    const status = dayStatus(key, d.getDay());
    return [
      mini ? styles.miniDay : styles.day,
      hasEvents && (mini ? styles.miniDayHasEvents : styles.dayHasEvents),
      status === "closed" && (mini ? styles.miniDayClosed : styles.dayClosed),
      status === "half" && (mini ? styles.miniDayHalf : styles.dayHalf),
      status === "weekend" && (mini ? styles.miniDayWeekend : styles.dayWeekend),
      viewMode === "month" && selectedDay === key && styles.daySelected,
      key === TODAY_KEY && (mini ? styles.miniDayToday : styles.dayToday),
    ]
      .filter(Boolean)
      .join(" ");
  };

  return (
    <div>
      <SeoHead
        title="School calendar · Cherry Hill · schoolz"
        description="District-wide and per-school calendar for Cherry Hill Public Schools - closures, early dismissals, deadlines, and events, searchable and filterable by school."
        path="/calendar"
      />
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>Calendar</h2>
        <div className="tabs" style={{ margin: 0 }}>
          <button className={`tab ${viewMode === "month" ? "active" : ""}`} onClick={() => setViewMode("month")}>
            Month
          </button>
          <button className={`tab ${viewMode === "year" ? "active" : ""}`} onClick={() => setViewMode("year")}>
            Year
          </button>
        </div>
      </div>

      {deepSchool && (
        <div className="scopeBar">
          <span>
            Only <b>{deepSchoolObj ? deepSchoolObj.short_name || deepSchoolObj.name : deepSchool}</b>
          </span>
          <button type="button" className="ghost" onClick={clearSchoolFilter}>
            Show all my schools
          </button>
        </div>
      )}

      {!deepSchool && showEmptySelectionNote && !isSearching && <p className="note">Every school in the district. Pick schools on "My schools" to narrow it down.</p>}

      {!isSearching && viewMode === "month" && (
        <>
          <div className={styles.monthNav}>
            <button className={styles.navButton} onClick={() => changeMonth(-1)} aria-label="Previous month">
              <IconChevronLeft className={styles.navIcon} />
            </button>
            <h2>{viewDate.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h2>
            <button className={styles.navButton} onClick={() => changeMonth(1)} aria-label="Next month">
              <IconChevronRight className={styles.navIcon} />
            </button>
          </div>

          <div className={styles.grid}>
            {WEEKDAYS.map((w) => (
              <div key={w} className={styles.weekday}>
                {w}
              </div>
            ))}
            {grid.map((d, idx) => {
              if (!d) return <div key={idx} className={`${styles.day} ${styles.dayEmpty}`} />;
              const key = dateKey(d);
              return (
                <button
                  key={idx}
                  type="button"
                  className={dayButtonClasses(d)}
                  aria-pressed={selectedDay === key}
                  aria-label={d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }) + (key === TODAY_KEY ? " (today)" : "")}
                  onClick={() => tapDay(key, d)}
                >
                  {d.getDate()}
                </button>
              );
            })}
          </div>

          <div className={styles.dayFilterRow}>
            <span className="note" style={{ margin: 0 }}>
              {selectedDay ? (selectedDay === TODAY_KEY ? `Today, ${selectedLabel}` : selectedLabel) : "Showing the whole month"}
            </span>
            {selectedDay && (
              <button className="ghost" onClick={showMonth}>
                Show month
              </button>
            )}
          </div>
        </>
      )}

      {!isSearching && viewMode === "year" && (
        <>
          <div className={styles.monthNav}>
            <button className={styles.navButton} onClick={() => changeYear(-1)} aria-label="Previous year">
              <IconChevronLeft className={styles.navIcon} />
            </button>
            <h2>{viewDate.getFullYear()}</h2>
            <button className={styles.navButton} onClick={() => changeYear(1)} aria-label="Next year">
              <IconChevronRight className={styles.navIcon} />
            </button>
          </div>

          <p className="note" style={{ marginTop: 0 }}>
            Tap any day to jump to that month.
          </p>

          <div className={styles.yearGrid}>
            {MONTH_NAMES.map((name, m) => {
              const cells = monthCells(viewDate.getFullYear(), m);
              const isCurrentMonth = m === new Date().getMonth() && viewDate.getFullYear() === new Date().getFullYear();
              return (
                <div className={styles.miniMonth} key={name}>
                  <div className={isCurrentMonth ? styles.miniMonthTitleCurrent : styles.miniMonthTitle}>{name}</div>
                  <div className={styles.miniGrid}>
                    {WEEKDAY_INITIALS.map((w, i) => (
                      <div className={styles.miniWeekday} key={i}>
                        {w}
                      </div>
                    ))}
                    {cells.map((d, idx) => {
                      if (!d) return <div key={idx} className={`${styles.miniDay} ${styles.miniDayEmpty}`} />;
                      const key = dateKey(d);
                      return (
                        <button
                          key={idx}
                          type="button"
                          className={dayButtonClasses(d, true)}
                          aria-label={d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
                          onClick={() => tapDay(key, d)}
                        >
                          {d.getDate()}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      <div className="filterChecks" style={{ margin: "14px 0" }}>
        <label className="filterCheck" title="Rotation markers: Day 1, Day 2, …">
          <input type="checkbox" checked={showDayRotation} onChange={(e) => setShowDayRotation(e.target.checked)} />
          Show day rotation
        </label>
        <label className="filterCheck" title="Hides board meetings and other district items - never closures, half days, or grading dates">
          <input type="checkbox" checked={excludeDistrict} onChange={(e) => setExcludeDistrict(e.target.checked)} />
          Exclude district
        </label>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.searchBox}>
          <input placeholder="Search all events…" value={search} onChange={(e) => setSearch(e.target.value)} />
          {search && (
            <button className={styles.searchClear} aria-label="Clear search" onClick={() => setSearch("")}>
              ×
            </button>
          )}
        </div>
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Events, deadlines, grading & initiatives</option>
          <option value="event">Events only</option>
          <option value="deadline">Deadlines only</option>
          <option value="initiative">Initiatives only</option>
          <option value="marking_period">Grading dates only</option>
        </select>
      </div>

      {isSearching && (
        <div className={styles.dayFilterRow}>
          <span className="note" style={{ margin: 0 }}>
            Search results for &ldquo;{searchTerm.trim()}&rdquo;
          </span>
          <button className="ghost" onClick={() => setSearch("")}>
            Back to calendar
          </button>
        </div>
      )}

      {viewMode !== "year" &&
        (rows.length === 0 ? (
          <div className="empty">{isSearching ? `No events match "${searchTerm.trim()}".` : `Nothing found${selectedDay ? " for this day" : " this month"}.`}</div>
        ) : (
          <div className="list">
            {rows.map(({ key, item, label }) => (
              <ItemRow item={item} color={label ? colorForName(label) : undefined} schoolName={label} highlighted={item.id === deepEvent} key={key} />
            ))}
          </div>
        ))}
    </div>
  );
}
