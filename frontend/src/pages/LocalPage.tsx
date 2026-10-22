import { can } from "../lib/permissions";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { IconChevronLeft, IconChevronRight } from "../components/icons";
import { SeasonalBanner } from "../components/SeasonalBanner";
import { SeoHead } from "../components/SeoHead";
import { Modal } from "../components/ui/Modal";
import { useAuth } from "../context/AuthContext";
import { NearControl } from "../components/NearControl";
import { googleCalendarQuickAddUrl, itemDateKeys, localDateKey, monthDay, timeOfDay } from "../lib/calendar";
import { type NearChoice, addNearParams, loadNearChoice, saveNearChoice } from "../lib/eventsNear";
import { MONTH_NAMES, WEEKDAYS, WEEKDAY_INITIALS, dateKey, endOfMonth, monthCells, startOfMonth } from "../lib/monthGrid";
import { usePrerenderReady } from "../lib/prerenderReady";
import { trackEvent } from "../lib/track";
import type { LocalEvent, LocalEventFacets, LocalEventRow } from "../types";
import styles from "./CalendarPage.module.css";
import { LOCALE } from "../lib/i18n";

/** Community events near Cherry Hill (libraries, townships, the Y, concerts),
 * from the local_events.refresh job - billz's events feed, ported. Same
 * month/year grid + list shape as /calendar; public like every other read. */

type ViewMode = "month" | "year";
const TODAY_KEY = dateKey(new Date());
const PAGE = 150;

const asItem = (e: LocalEventRow & { description?: string | null }) => ({
  title: e.title,
  description: e.description ?? null,
  start_date: e.start_time,
  end_date: e.end_time,
  is_all_day: e.all_day,
});
const labelize = (s: string) => s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

function price(e: LocalEventRow): string | null {
  if (e.is_free) return "Free";
  if (e.price_min == null) return null;
  const f = (n: number) => `$${n % 1 ? n.toFixed(2) : n}`;
  return e.price_max != null && e.price_max !== e.price_min ? `${f(e.price_min)}–${f(e.price_max)}` : f(e.price_min);
}

export function LocalPage() {
  const { user } = useAuth();
  const isAdmin = can(user, "scans.view");
  const [viewMode, setViewMode] = useState<ViewMode>("month");
  const [viewDate, setViewDate] = useState(() => startOfMonth(new Date()));
  const [selectedDay, setSelectedDay] = useState<string | null>(TODAY_KEY);
  const [items, setItems] = useState<LocalEventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [days, setDays] = useState<Record<string, number>>({});
  const [daysKey, setDaysKey] = useState<string | null>(null);
  const [facets, setFacets] = useState<LocalEventFacets>({ categories: [], sources: [] });
  const [search, setSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [category, setCategory] = useState("");
  const [source, setSource] = useState("");
  const [freeOnly, setFreeOnly] = useState(false);
  const [nearChoice, setNearChoice] = useState<NearChoice>(loadNearChoice);
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<LocalEventRow | null>(null);
  const [scrollToToday, setScrollToToday] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setSearchTerm(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const range = useMemo(() => {
    if (viewMode === "year") return { start: new Date(viewDate.getFullYear(), 0, 1), end: new Date(viewDate.getFullYear(), 11, 31, 23, 59, 59) };
    return { start: startOfMonth(viewDate), end: endOfMonth(viewDate) };
  }, [viewDate, viewMode]);

  const { near, radius } = nearChoice;
  const nearKey = [near.lat, near.lng, radius].join(",");
  const filterKey = [range.start.toISOString(), searchTerm, category, source, freeOnly, nearKey].join("|");
  // The list is only shown in the month view or for a search. A picked day
  // loads just that day; the whole month (or a search) loads every row of
  // the range. The grid's dots come from /days either way, so a busy month
  // never loses its last days to the list's cap.
  const showList = viewMode === "month" || !!searchTerm;
  const listDay = viewMode === "month" && selectedDay && !searchTerm ? selectedDay : null;
  const queryKey = [filterKey, showList, listDay].join("|");

  const changeNear = (choice: NearChoice) => {
    setNearChoice(choice);
    saveNearChoice(choice);
    trackEvent("local_near", { method: choice.near.kind, radius: choice.radius ?? "any" });
  };

  const filterParams = () => {
    const q = new URLSearchParams();
    if (searchTerm) q.set("q", searchTerm);
    if (category) q.set("categories", category);
    if (source) q.set("source", source);
    if (freeOnly) q.set("is_free", "true");
    addNearParams(q, nearChoice);
    return q;
  };

  useEffect(() => {
    const q = filterParams();
    q.set("start", range.start.toISOString());
    q.set("end", range.end.toISOString());
    let cancelled = false;
    apiFetch(`/local-events/days?${q}`)
      .then((r) => (r.ok ? r.json() : { days: {} }))
      .then((d: { days: Record<string, number> }) => {
        if (cancelled) return;
        setDays(d.days);
        setDaysKey(filterKey);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  useEffect(() => {
    if (!showList) return;
    const q = filterParams();
    if (listDay) q.set("day", listDay);
    else {
      q.set("start", range.start.toISOString());
      q.set("end", range.end.toISOString());
    }
    q.set("limit", "6000");
    let cancelled = false;
    apiFetch(`/local-events/rows?${q}`)
      .then((r) => (r.ok ? r.json() : { items: [], total: 0 }))
      .then((d: { items: LocalEventRow[]; total: number }) => {
        if (cancelled) return;
        setItems(d.items);
        setTotal(d.total);
        setShown(PAGE);
        setLoadedKey(queryKey);
        if (searchTerm) trackEvent("local_search", { result_count: d.total, query_length: searchTerm.length });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  useEffect(() => {
    const q = new URLSearchParams({ start: range.start.toISOString(), end: range.end.toISOString() });
    addNearParams(q, nearChoice);
    apiFetch(`/local-events/facets?${q}`)
      .then((r) => (r.ok ? r.json() : { categories: [], sources: [] }))
      .then(setFacets);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range, nearKey]);

  const eventsByDay = useMemo(() => new Map(Object.entries(days)), [days]);

  const listed = useMemo(
    () => (selectedDay && viewMode === "month" ? items.filter((e) => itemDateKeys(asItem(e)).includes(selectedDay)) : items),
    [items, selectedDay, viewMode],
  );

  // "Show month" lands on today, like /calendar and the lunch page.
  useEffect(() => {
    if (!scrollToToday || selectedDay || loadedKey !== queryKey) return;
    setScrollToToday(false);
    if (!TODAY_KEY.startsWith(dateKey(viewDate).slice(0, 7))) return;
    const idx = listed.findIndex((e) => itemDateKeys(asItem(e)).some((k) => k >= TODAY_KEY));
    if (idx < 0) return;
    if (idx >= shown) setShown(idx + PAGE);
    requestAnimationFrame(() => document.getElementById(`local-${listed[idx].id}`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [scrollToToday, selectedDay, loadedKey, queryKey, listed, shown, viewDate]);

  // Without this every crawler render of /local waited out the prerender
  // timeout and failed - it's in the sitemap, but Google only ever got errors.
  usePrerenderReady((!showList || loadedKey === queryKey) && daysKey === filterKey);

  const changeMonth = (delta: number) => {
    setViewDate((d) => (viewMode === "year" ? new Date(d.getFullYear() + delta, d.getMonth(), 1) : new Date(d.getFullYear(), d.getMonth() + delta, 1)));
    setSelectedDay(null);
  };

  const tapDay = (key: string, d: Date) => {
    if (viewMode === "year") {
      setViewDate(startOfMonth(d));
      setViewMode("month");
      setSelectedDay(key);
      return;
    }
    setSelectedDay((cur) => (cur === key ? null : key));
  };

  const dayClass = (d: Date, mini = false) => {
    const key = dateKey(d);
    const dow = d.getDay();
    return [
      mini ? styles.miniDay : styles.day,
      eventsByDay.has(key) && (mini ? styles.miniDayHasEvents : styles.dayHasEvents),
      (dow === 0 || dow === 6) && (mini ? styles.miniDayWeekend : styles.dayWeekend),
      viewMode === "month" && selectedDay === key && styles.daySelected,
      key === TODAY_KEY && (mini ? styles.miniDayToday : styles.dayToday),
    ]
      .filter(Boolean)
      .join(" ");
  };

  const selectedLabel = selectedDay
    ? new Date(selectedDay + "T12:00:00Z").toLocaleDateString(LOCALE, { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" })
    : null;

  return (
    <div>
      <SeoHead
        title="Local events · Cherry Hill & South Jersey · schoolz"
        description="Free and family community events around Cherry Hill and South Jersey - library programs, township events, the Y, concerts and more, in one calendar."
        path="/local"
      />
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>Local</h2>
        <div className="tabs" style={{ margin: 0 }}>
          <button className={`tab ${viewMode === "month" ? "active" : ""}`} onClick={() => setViewMode("month")}>
            Month
          </button>
          <button className={`tab ${viewMode === "year" ? "active" : ""}`} onClick={() => setViewMode("year")}>
            Year
          </button>
        </div>
      </div>
      <SeasonalBanner />
      <p className="note" style={{ marginTop: 0 }}>
        Community events around South Jersey - libraries, townships, the Y, concerts and more.
        {isAdmin && (
          <>
            {" "}
            Sources are managed in <Link to="/admin/scans">Admin → Scans</Link> (Local events refresh).
          </>
        )}
      </p>
      <NearControl choice={nearChoice} onChange={changeNear} />

      <div className={styles.monthNav}>
        <button className={styles.navButton} onClick={() => changeMonth(-1)} aria-label={viewMode === "year" ? "Previous year" : "Previous month"}>
          <IconChevronLeft className={styles.navIcon} />
        </button>
        <h2>{viewMode === "year" ? viewDate.getFullYear() : viewDate.toLocaleDateString(LOCALE, { month: "long", year: "numeric" })}</h2>
        <button className={styles.navButton} onClick={() => changeMonth(1)} aria-label={viewMode === "year" ? "Next year" : "Next month"}>
          <IconChevronRight className={styles.navIcon} />
        </button>
      </div>

      {viewMode === "month" ? (
        <>
          <div className={styles.grid}>
            {WEEKDAYS.map((w) => (
              <div key={w} className={styles.weekday}>
                {w}
              </div>
            ))}
            {monthCells(viewDate.getFullYear(), viewDate.getMonth()).map((d, idx) => {
              if (!d) return <div key={idx} className={`${styles.day} ${styles.dayEmpty}`} />;
              const key = dateKey(d);
              return (
                <button key={idx} type="button" className={dayClass(d)} aria-pressed={selectedDay === key} onClick={() => tapDay(key, d)}>
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
              <button
                className="ghost"
                onClick={() => {
                  setSelectedDay(null);
                  setScrollToToday(true);
                }}
              >
                Show month
              </button>
            )}
          </div>
        </>
      ) : (
        <div className={styles.yearGrid}>
          {MONTH_NAMES.map((name, m) => (
            <div className={styles.miniMonth} key={name}>
              <div className={styles.miniMonthTitle}>{name}</div>
              <div className={styles.miniGrid}>
                {WEEKDAY_INITIALS.map((w, i) => (
                  <div className={styles.miniWeekday} key={i}>
                    {w}
                  </div>
                ))}
                {monthCells(viewDate.getFullYear(), m).map((d, idx) =>
                  d ? (
                    <button key={idx} type="button" className={dayClass(d, true)} onClick={() => tapDay(dateKey(d), d)}>
                      {d.getDate()}
                    </button>
                  ) : (
                    <div key={idx} className={`${styles.miniDay} ${styles.miniDayEmpty}`} />
                  ),
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className={`${styles.toolbar} ${styles.filters}`} style={{ marginTop: 14 }}>
        <div className={styles.searchBox}>
          <input placeholder="Search events, venues…" value={search} onChange={(e) => setSearch(e.target.value)} />
          {search && (
            <button className={styles.searchClear} aria-label="Clear search" onClick={() => setSearch("")}>
              ×
            </button>
          )}
        </div>
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {facets.categories.map((c) => (
            <option key={c.value} value={c.value}>
              {labelize(c.value)} ({c.count})
            </option>
          ))}
        </select>
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Source">
          <option value="">All sources</option>
          {facets.sources.map((s) => (
            <option key={s.value} value={s.value}>
              {labelize(s.value)} ({s.count})
            </option>
          ))}
        </select>
      </div>
      <div className="filterChecks" style={{ margin: "4px 0 12px" }}>
        <label className="filterCheck">
          <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
          Free only
        </label>
        {showList && total > items.length && <span className="note" style={{ margin: 0 }}>Showing the first {items.length} of {total} - narrow the filters to see the rest.</span>}
      </div>

      {(viewMode === "month" || searchTerm) &&
        (listed.length === 0 ? (
          <div className="empty">
            {loadedKey === queryKey
              ? `Nothing found${selectedDay ? " for this day" : " this month"}${radius !== null ? ` within ${radius} miles of ${near.label}` : ""}.`
              : "Loading…"}
          </div>
        ) : (
          <>
            <div className="list">
              {listed.slice(0, shown).map((e) => (
                <LocalRow key={e.id} event={e} onOpen={() => setOpen(e)} rangeStart={dateKey(range.start)} rangeEnd={dateKey(range.end)} />
              ))}
            </div>
            {listed.length > shown && (
              <button className="btn" style={{ margin: "12px auto", display: "block" }} onClick={() => setShown((n) => n + PAGE)}>
                Show more ({listed.length - shown} left)
              </button>
            )}
          </>
        ))}

      <LocalEventSheet event={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function LocalRow({ event: e, onOpen, rangeStart, rangeEnd }: { event: LocalEventRow; onOpen: () => void; rangeStart?: string; rangeEnd?: string }) {
  const allKeys = itemDateKeys(asItem(e));
  // A multi-day event (e.g. a theatre run spanning two months) still passes the
  // backend's overlap filter for whichever month is in view; clip the label to
  // that month's own days so a run that started last month doesn't show its
  // original, out-of-view start date on this list.
  const keys = rangeStart && rangeEnd ? allKeys.filter((k) => k >= rangeStart && k <= rangeEnd) : allKeys;
  const visible = keys.length > 0 ? keys : allKeys;
  const md = monthDay(visible[0] ?? localDateKey(e.start_time));
  const last = visible.length > 1 ? monthDay(visible[visible.length - 1]) : null;
  const p = price(e);
  return (
    <button type="button" className="row localRow" id={`local-${e.id}`} onClick={onOpen}>
      <div className="when">
        {md.month}
        <b>{last && last.month === md.month ? `${md.day}–${last.day}` : md.day}</b>
      </div>
      <div className="what">
        <div className="ttl">{e.title}</div>
        <div className="desc">{[!e.all_day && timeOfDay(e.start_time), e.venue_name, e.miles != null && `${e.miles} mi`].filter(Boolean).join(" · ")}</div>
        <div className="tagrow">
          {p && <span className={`tag${e.is_free ? " new" : ""}`}>{p}</span>}
          {e.categories.slice(0, 3).map((c) => (
            <span className="tag" key={c}>
              {labelize(c)}
            </span>
          ))}
        </div>
      </div>
    </button>
  );
}

function LocalEventSheet({ event: row, onClose }: { event: LocalEventRow | null; onClose: () => void }) {
  // The row has what the list shows; the rest (description, address, image,
  // link) is fetched when the sheet opens.
  const [full, setFull] = useState<LocalEvent | null>(null);
  useEffect(() => {
    if (!row) return;
    let cancelled = false;
    apiFetch(`/local-events/${encodeURIComponent(row.id)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: LocalEvent | null) => {
        if (!cancelled) setFull(d);
      });
    return () => {
      cancelled = true;
      setFull(null);
    };
  }, [row]);
  if (!row) return null;
  const e: LocalEventRow & Partial<LocalEvent> = full && full.id === row.id ? { ...full, miles: row.miles } : row;
  const cal = googleCalendarQuickAddUrl(asItem(e));
  const keys = itemDateKeys(asItem(e));
  const fmt = (k: string, wd: boolean) =>
    new Date(k + "T12:00:00Z").toLocaleDateString(LOCALE, { ...(wd ? { weekday: "long" } : {}), month: "long", day: "numeric", timeZone: "UTC" });
  const dates = keys.length > 1 ? `${fmt(keys[0], false)} – ${fmt(keys[keys.length - 1], false)}` : fmt(keys[0] ?? localDateKey(e.start_time), true);
  const when = e.all_day ? dates : `${dates} · ${timeOfDay(e.start_time)}${e.end_time ? `–${timeOfDay(e.end_time)}` : ""}`;
  const p = price(e);
  return (
    <Modal open onClose={onClose} title={e.title} subtitle={when}>
      {e.image_url && <img className="eventSheet-img" src={e.image_url} alt="" loading="lazy" />}
      {(e.venue_name || e.venue_address) && (
        <p className="eventSheet-venue">
          <b>{e.venue_name}</b>
          {e.venue_address && (
            <>
              {e.venue_name && <br />}
              <a href={`https://maps.google.com/?q=${encodeURIComponent(e.venue_address)}`} target="_blank" rel="noreferrer">
                {e.venue_address}
              </a>
            </>
          )}
        </p>
      )}
      {e.description && <p className="eventSheet-desc">{e.description}</p>}
      <div className="tagrow" style={{ marginBottom: 14 }}>
        {p && <span className={`tag${e.is_free ? " new" : ""}`}>{p}</span>}
        {e.categories.map((c) => (
          <span className="tag" key={c}>
            {labelize(c)}
          </span>
        ))}
        <span className="tag district">{labelize(e.source)}</span>
      </div>
      <div className="eventSheet-actions">
        {cal && (
          <a className="btn btn-primary" href={cal} target="_blank" rel="noreferrer" onClick={() => trackEvent("action", { action: "add_to_calendar", method: "local_sheet" })}>
            Add to calendar
          </a>
        )}
        {e.url && (
          <a className="btn" href={e.url} target="_blank" rel="noreferrer">
            Event page
          </a>
        )}
      </div>
    </Modal>
  );
}
