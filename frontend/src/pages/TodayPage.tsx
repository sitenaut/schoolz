import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { DayCard } from "../components/today";
import { IconPin } from "../components/icons";
import { SeasonalBanner } from "../components/SeasonalBanner";
import { SeoHead } from "../components/SeoHead";
import { localDateKey, monthDay } from "../lib/calendar";
import { useMySchools } from "../lib/mySchools";
import { SITE_URL } from "../lib/site";
import { usePrerenderReady } from "../lib/prerenderReady";
import { trackMeasurement } from "../lib/track";
import type { SchoolContentItem, SchoolToday } from "../types";
import { useTranslation } from "react-i18next";
import { LOCALE } from "../lib/i18n";

function HomeSeo() {
  const { t } = useTranslation();
  return (
    <SeoHead
      title={t("schoolz · What's happening at your kids' school today?")}
      description={t("Snow day? Early dismissal? What's for lunch? See your kids' school day at a glance: status, bell times, lunch, buses and who to call. Free, no account.")}
      path="/"
      image={`${SITE_URL}/icon-512.png`}
    />
  );
}

/** The home page: one day-card per active school, with any district-wide
 * closure/early-dismissal in the next week pulled up into a banner so
 * it's read once, not once per card. Every school on the visitor's list
 * is fetched (so toggling one on/off in the top ribbon is instant, no
 * refetch), but only the active ones render. */
export function TodayPage() {
  const { t } = useTranslation();
  const { mySchools, activeSchools, loading, colorFor, isFiltered, districtsById } = useMySchools();
  const [cards, setCards] = useState<Record<string, SchoolToday>>({});
  const readyStart = useRef(performance.now());
  const readyReported = useRef(false);

  useEffect(() => {
    let cancelled = false;
    mySchools.forEach((s) => {
      apiFetch(`/schools/${s.slug}/today`)
        .then((r) => (r.ok ? r.json() : null))
        .then((today: SchoolToday | null) => {
          if (today && !cancelled) setCards((c) => ({ ...c, [s.id]: today }));
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
        <HomeSeo />
        <h1 className="sr-only">{t("Today at your kids' schools")}</h1>
        <p className="note">{t("Loading…")}</p>
      </>
    );
  if (mySchools.length === 0)
    return (
      <>
        <HomeSeo />
        <h1 className="sr-only">{t("Today at your kids' schools")}</h1>
        <div className="empty">
          <p>
            <strong>{t("Pick your kids' schools")}</strong> {t("to see today's status, bell schedules, lunch, and bus info here.")}
          </p>
          <p>
            <Link to="/start" className="btn btn-primary">
              {t("Pick your schools")}
            </Link>
          </p>
        </div>
        {/* Local and seasonal need no school. On a phone the Local tab is the
            sixth item, off the edge of the bar, so without these the picker
            above read as the only way into the site. */}
        <p className="note" style={{ margin: "18px 0 8px" }}>
          {t("No school needed")}
        </p>
        <SeasonalBanner />
        <Link className="link-card" to="/local">
          <span className="ico">
            <IconPin />
          </span>
          <span>
            <b>{t("Local events")}</b>
            <small>{t("Things to do around South Jersey and Philadelphia")} →</small>
          </span>
        </Link>
      </>
    );

  const first = cards[activeSchools[0]?.id] ?? cards[mySchools[0].id];
  const heading = first
    ? new Date(first.date + "T12:00:00Z").toLocaleDateString(LOCALE, { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" })
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
      <HomeSeo />
      <h1 className="eyebrow" style={{ margin: "0 0 10px" }}>
        {heading}
        {isFiltered && <span style={{ marginLeft: 8, fontWeight: 600 }}>· {t("showing {{a}} of {{b}}", { a: activeSchools.length, b: mySchools.length })}</span>}
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
              {a.scope === "district" && a.district_id ? t("(all {{district}} schools)", { district: districtsById.get(a.district_id)?.name ?? t("district") }) : ""}
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
              {t("Loading…")}
            </p>
          </section>
        ),
      )}

      <p className="fine">
        {t("Pulled from each school's newsletter and website, the district calendar, and the district lunch menu.")} <Link to="/schools">{t("All schools")}</Link>
      </p>
    </>
  );
}
