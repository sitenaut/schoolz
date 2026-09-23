import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { DayCard } from "../components/today";
import { SeoHead } from "../components/SeoHead";
import { localDateKey, monthDay } from "../lib/calendar";
import { useMySchools } from "../lib/mySchools";
import { usePrerenderReady } from "../lib/prerenderReady";
import { trackMeasurement } from "../lib/track";
import type { SchoolContentItem, SchoolToday } from "../types";

const HOME_SEO = (
  <SeoHead
    title="schoolz · Cherry Hill — Today at your kids' schools"
    description="Live school-day status, bell schedules, lunch menus, bus info, and calendar dates for Cherry Hill Public Schools - free, public, no account needed."
    path="/"
  />
);

/** The home page: one day-card per active school, with any district-wide
 * closure/early-dismissal in the next week pulled up into a banner so
 * it's read once, not once per card. Every school on the visitor's list
 * is fetched (so toggling one on/off in the top ribbon is instant, no
 * refetch), but only the active ones render. */
export function TodayPage() {
  const { mySchools, activeSchools, loading, colorFor, isFiltered } = useMySchools();
  const [cards, setCards] = useState<Record<string, SchoolToday>>({});
  const readyStart = useRef(performance.now());
  const readyReported = useRef(false);

  useEffect(() => {
    let cancelled = false;
    mySchools.forEach((s) => {
      apiFetch(`/schools/${s.slug}/today`)
        .then((r) => (r.ok ? r.json() : null))
        .then((t: SchoolToday | null) => {
          if (t && !cancelled) setCards((c) => ({ ...c, [s.id]: t }));
        })
        .catch(() => {
          /* one school's fetch failing shouldn't take the others down */
        });
    });
    return () => {
      cancelled = true;
    };
  }, [mySchools]);

  useEffect(() => {
    if (readyReported.current || mySchools.length === 0) return;
    if (Object.keys(cards).length < mySchools.length) return;
    readyReported.current = true;
    trackMeasurement("today_ready", performance.now() - readyStart.current, { schools: mySchools.length });
  }, [cards, mySchools]);

  usePrerenderReady(!loading);

  if (loading)
    return (
      <>
        {HOME_SEO}
        <h1 className="sr-only">Today at your kids' schools</h1>
        <p className="note">Loading…</p>
      </>
    );
  if (mySchools.length === 0)
    return (
      <>
        {HOME_SEO}
        <h1 className="sr-only">Today at your kids' schools</h1>
        <div className="empty">
          <p>
            <strong>Pick your kids' schools</strong> to see today's status, bell schedules, lunch, and bus info here.
          </p>
          <p>
            <Link to="/start" className="btn btn-primary">
              Pick your schools
            </Link>
          </p>
        </div>
      </>
    );

  const first = cards[activeSchools[0]?.id] ?? cards[mySchools[0].id];
  const heading = first
    ? new Date(first.date + "T12:00:00Z").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" })
    : "";

  // District-wide alerts appear on every card - show each once, only for
  // the schools currently active in the ribbon filter.
  const alerts = new Map<string, SchoolContentItem>();
  for (const s of activeSchools) {
    for (const a of cards[s.id]?.alerts ?? []) {
      const key = `${localDateKey(a.start_date!)}|${a.scope === "district" ? "d" : s.id}|${a.title}`;
      if (!alerts.has(key)) alerts.set(key, a);
    }
  }

  return (
    <>
      {HOME_SEO}
      <h1 className="eyebrow" style={{ margin: 0 }}>
        {heading}
        {isFiltered && <span style={{ marginLeft: 8, fontWeight: 600 }}>· showing {activeSchools.length} of {mySchools.length}</span>}
      </h1>

      {[...alerts.values()].map((a) => {
        const md = monthDay(localDateKey(a.start_date!));
        const closed = /closed/i.test(a.title);
        return (
          <div className={`banner ${closed ? "bad" : ""}`} key={a.id}>
            <span aria-hidden="true">⚠</span>
            <span>
              <b>
                {md.month} {md.day}
              </b>{" "}
              · {a.title}
              {a.scope === "district" ? " (all Cherry Hill schools)" : ""}
            </span>
          </div>
        );
      })}

      {activeSchools.map((s) =>
        cards[s.id] ? (
          <DayCard data={cards[s.id]} color={colorFor(s.id)} key={s.id} />
        ) : (
          <section className="day" style={{ ["--c" as string]: colorFor(s.id) }} key={s.id}>
            <header>
              <h2>{s.short_name || s.name}</h2>
            </header>
            <p className="note" style={{ padding: "0 14px 12px" }}>
              Loading…
            </p>
          </section>
        ),
      )}

      <p className="fine">
        Pulled from each school's newsletter and website, the district calendar, and the district lunch menu. <Link to="/schools">All schools</Link>
      </p>
    </>
  );
}
