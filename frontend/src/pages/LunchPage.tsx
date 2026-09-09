import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { apiFetch } from "../api";
import { localDateKey, monthDay, todayKey } from "../lib/calendar";
import { schoolTypeLabel } from "../lib/schoolType";
import { useMySchools } from "../lib/mySchools";
import type { LunchMenu } from "../types";

export function LunchPage() {
  const { mySchools, activeSchools, loading, colorFor } = useMySchools();
  const [active, setActive] = useState<string | null>(null);
  const [menu, setMenu] = useState<LunchMenu | null | undefined>(undefined);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());

  useEffect(() => {
    // Keep the selected tab inside whatever the ribbon filter currently
    // shows - picks the first active school on load, and jumps off a
    // school that just got hidden via the ribbon.
    if (activeSchools.length === 0) return;
    if (!active || !activeSchools.some((s) => s.slug === active)) {
      setActive(activeSchools[0].slug);
    }
  }, [activeSchools, active]);

  useEffect(() => {
    if (!active) return;
    setMenu(undefined);
    apiFetch(`/schools/${active}/lunch-menu`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setMenu);
  }, [active]);

  const tk = todayKey();
  const items = menu?.items ?? [];

  // Every day in the month is listed (not just upcoming ones), scrolled
  // to whichever row is today - or the nearest day after it, if today
  // itself has no entry (a weekend, a break) - so today lands as the
  // first visible row without hiding the rest of the month above it.
  useEffect(() => {
    if (!scrollRef.current || items.length === 0) return;
    const onOrAfterToday = items.find((i) => localDateKey(i.menu_date) >= tk);
    const targetKey = onOrAfterToday ? localDateKey(onOrAfterToday.menu_date) : null;
    const el = targetKey ? rowRefs.current.get(targetKey) : null;
    const container = scrollRef.current;
    if (el) {
      container.scrollTop = el.offsetTop - container.offsetTop;
    } else {
      container.scrollTop = 0;
    }
  }, [items, tk]);

  const school = mySchools.find((s) => s.slug === active);

  const rows = useMemo(
    () =>
      items.map((i) => {
        const key = localDateKey(i.menu_date);
        const md = monthDay(key);
        const wd = new Date(key + "T12:00:00Z").toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" });
        return { item: i, key, md, wd, isToday: key === tk, isPast: key < tk };
      }),
    [items, tk],
  );

  if (loading) return <p className="note">Loading…</p>;
  if (mySchools.length === 0) return <Navigate to="/start" replace />;

  return (
    <>
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>Lunch</h2>
        {menu && !menu.source_pdf_url.startsWith("newsletter:") && (
          <a href={menu.source_pdf_url} target="_blank" rel="noreferrer">
            {menu.period_label} PDF
          </a>
        )}
      </div>
      {activeSchools.length > 1 && (
        <div className="chips">
          {activeSchools.map((s) => (
            <button className="chip" aria-pressed={s.slug === active} style={{ ["--c" as string]: colorFor(s.id) }} onClick={() => setActive(s.slug)} key={s.id}>
              <span className="dot" />
              {s.short_name || s.name}
            </button>
          ))}
        </div>
      )}
      {menu === undefined ? (
        <p className="note">Loading…</p>
      ) : menu === null ? (
        <div className="empty">No lunch menu on file for {school?.short_name || school?.name} yet.</div>
      ) : rows.length === 0 ? (
        <div className="empty">No days listed for {menu.period_label} yet.</div>
      ) : (
        <>
          <div className="list scrollList" ref={scrollRef}>
            {rows.map(({ item, key, md, wd, isToday, isPast }) => (
              <div
                className={`row ${isToday ? "rowToday" : ""}`}
                ref={(el) => {
                  if (el) rowRefs.current.set(key, el);
                  else rowRefs.current.delete(key);
                }}
                style={isPast && !isToday ? { opacity: 0.55 } : undefined}
                key={item.id}
              >
                <div className="when">
                  {wd}
                  <b>{md.day}</b>
                  {isToday && <span className="todayBadge">Today</span>}
                </div>
                <div className="what">
                  <div className="ttl">{item.description}</div>
                  {item.notes && <div className="desc">{item.notes}</div>}
                </div>
              </div>
            ))}
          </div>
          <p className="note" style={{ marginTop: 8 }}>
            {menu.period_label} · {schoolTypeLabel(school?.school_type ?? null) ? `${schoolTypeLabel(school?.school_type ?? null)} menu` : "school menu"} · every day of the month, scrolled to today.
          </p>
        </>
      )}
      <p className="fine">
        Something look off? <Link to={`/schools/${active}`}>Open the school page</Link>.
      </p>
    </>
  );
}
