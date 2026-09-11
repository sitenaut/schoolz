import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMySchools } from "../lib/mySchools";
import { apiFetch } from "../api";
import { ItemRow } from "../components/today";
import { SchoolPicker } from "../components/SchoolPicker";
import { IconChevronLeft, IconChevronRight } from "../components/icons";
import type { SchoolContentItem } from "../types";
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
  const { activeSchools, colorFor, loading } = useMySchools();
  const [params] = useSearchParams();
  const deepSchool = params.get("school");
  // Which schools' dates are shown - owned by the picker. Seeded once
  // data is ready: from a school page's "see all dates" deep link if there
  // is one, else from whatever the top ribbon currently shows. After that
  // the picker is the source of truth (any number of schools, mine or not).
  const [selected, setSelected] = useState<string[] | null>(null);
  useEffect(() => {
    if (loading || selected !== null) return;
    setSelected(deepSchool ? [deepSchool] : activeSchools.map((s) => s.slug));
  }, [loading, selected, deepSchool, activeSchools]);
  const [viewMode, setViewMode] = useState<ViewMode>("month");
  const [viewDate, setViewDate] = useState(() => startOfMonth(new Date()));
  const [items, setItems] = useState<SchoolContentItem[]>([]);
  // Lands filtered to today - both a default and a live filter, cleared
  // by tapping today's cell again, any other cell, or "Show month".
  const [selectedDay, setSelectedDay] = useState<string | null>(TODAY_KEY);
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const isSearching = searchTerm.trim().length > 0;

  const schoolSlugs = selected ?? [];
  const schoolIdsKey = schoolSlugs.join(",");

  // Debounced so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setSearchTerm(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (loading || selected === null) return;
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
    apiFetch(`/calendar?${q.toString()}`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setItems);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewDate, viewMode, schoolIdsKey, category, loading, isSearching, searchTerm, selected === null]);

  const colorForName = (name: string | null) => {
    const s = activeSchools.find((m) => (m.short_name || m.name) === name);
    return s ? colorFor(s.id) : "var(--district)";
  };
  const showEmptySelectionNote = (selected?.length ?? 0) === 0;

  const eventsByDay = useMemo(() => {
    const map = new Map<string, SchoolContentItem[]>();
    for (const item of items) {
      if (!item.start_date) continue;
      const key = item.start_date.slice(0, 10);
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    return map;
  }, [items]);

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

  const rows = useMemo(() => {
    const list = !isSearching && selectedDay && viewMode === "month" ? items.filter((i) => i.start_date?.slice(0, 10) === selectedDay) : items;
    return [...list].sort((a, b) => (a.start_date ?? "") < (b.start_date ?? "") ? -1 : 1);
  }, [items, selectedDay, isSearching, viewMode]);

  const selectedLabel = selectedDay
    ? new Date(selectedDay + "T12:00:00Z").toLocaleDateString(undefined, {
        weekday: "long",
        month: "long",
        day: "numeric",
        ...(selectedDay.slice(0, 4) !== TODAY_KEY.slice(0, 4) ? { year: "numeric" } : {}),
      })
    : null;

  const dayButtonClasses = (d: Date, mini = false) => {
    const key = dateKey(d);
    const hasEvents = eventsByDay.has(key);
    return [
      mini ? styles.miniDay : styles.day,
      hasEvents && (mini ? styles.miniDayHasEvents : styles.dayHasEvents),
      viewMode === "month" && selectedDay === key && styles.daySelected,
      key === TODAY_KEY && (mini ? styles.miniDayToday : styles.dayToday),
    ]
      .filter(Boolean)
      .join(" ");
  };

  return (
    <div>
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

      <SchoolPicker selected={selected ?? []} onChange={setSelected} />
      {showEmptySelectionNote && !isSearching && <p className="note">Every school in the district. Pick schools above to narrow it down.</p>}

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
              <button className="ghost" onClick={() => setSelectedDay(null)}>
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
          <option value="">Events, deadlines & initiatives</option>
          <option value="event">Events only</option>
          <option value="deadline">Deadlines only</option>
          <option value="initiative">Initiatives only</option>
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
            {rows.map((i) => (
              <ItemRow item={i} color={i.scope === "school" ? colorForName(i.school_name) : undefined} schoolName={i.scope === "school" ? i.school_name : null} key={i.id} />
            ))}
          </div>
        ))}
    </div>
  );
}
