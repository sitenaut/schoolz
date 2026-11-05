import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../api";
import { IconChevronRight, IconMessage } from "./icons";
import { timeOfDay } from "../lib/calendar";
import { openChat } from "../lib/chatLauncher";
import { type DayOffPlan, dayOffNear } from "../lib/dayOff";
import { addNearParams, loadNearChoice } from "../lib/eventsNear";
import { LOCALE } from "../lib/i18n";
import { trackEvent } from "../lib/track";
import type { LocalEventRow } from "../types";

// A feed that gives only a date lands its events at midnight, which is no
// time to tell anyone (prod's month-long reading challenges, some shows).
const MIDNIGHT = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hourCycle: "h23" });
const untimed = (e: LocalEventRow) => e.all_day || MIDNIGHT.format(new Date(e.start_time)) === "00:00";

/** A day off school, today or a few days out (lib/dayOff.ts): three things
 * to do near the school, the whole day on /local, and the chatbot with the
 * question already typed. Sits below the school cards, never above: it
 * arrives after them and would push them down. */
export function DayOffCard({ plan }: { plan: DayOffPlan }) {
  const { t } = useTranslation();
  // Held with the query they answer, so a changed place shows "Loading…"
  // rather than the last place's picks.
  const [loaded, setLoaded] = useState<{ query: string; items: LocalEventRow[] } | null>(null);
  const { choice, place, town } = useMemo(() => dayOffNear(loadNearChoice(), plan.schools), [plan.schools]);

  const params = new URLSearchParams({ day: plan.date, audience: plan.audience });
  addNearParams(params, choice);
  const query = params.toString();
  useEffect(() => {
    let cancelled = false;
    apiFetch(`/local-events/day-off?${query}`)
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d: { items: LocalEventRow[] }) => {
        if (!cancelled) setLoaded({ query, items: d.items });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ query, items: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [query]);
  const picks = loaded?.query === query ? loaded.items : null;

  // Once per day off, with what it offered, so taps can be read against it.
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (picks === null || reported.current === plan.date) return;
    reported.current = plan.date;
    trackEvent("day_off_shown", { days_ahead: plan.daysAhead, picks: picks.length, audience: plan.audience });
  }, [picks, plan]);

  const noon = new Date(plan.date + "T12:00:00Z");
  const weekday = noon.toLocaleDateString(LOCALE, { weekday: "long", timeZone: "UTC" });
  const longDay = noon.toLocaleDateString(LOCALE, { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" });
  const today = plan.daysAhead === 0;
  const heading = today ? t("No school today") : plan.daysAhead === 1 ? t("No school tomorrow") : t("No school {{day}}", { day: weekday });
  const sub = [plan.label, !plan.allOut && plan.schools.map((s) => s.short_name || s.name).join(", ")].filter(Boolean).join(" · ");
  const kids = plan.audience === "kids";

  const ask = () => {
    const draft = today
      ? kids
        ? t("No school today. What can we do with the kids near {{place}}?", { place: town })
        : t("No school today. What can a teenager do near {{place}}?", { place: town })
      : kids
        ? t("No school on {{day}}. What can we do with the kids near {{place}}?", { place: town, day: longDay })
        : t("No school on {{day}}. What can a teenager do near {{place}}?", { place: town, day: longDay });
    trackEvent("day_off_ask", { days_ahead: plan.daysAhead });
    openChat(draft, "day_off");
  };

  return (
    <section className="day dayOff" id="day-off" aria-labelledby="day-off-heading">
      <header>
        <div>
          <h2 id="day-off-heading">{heading}</h2>
          {sub && <div className="kids">{sub}</div>}
        </div>
      </header>
      <p className="dayOff-k">{place ? t("Things to do near {{place}}", { place }) : t("Things to do nearby")}</p>
      <ul className="next">
        {picks === null ? (
          <li className="dayOff-note">{t("Loading…")}</li>
        ) : picks.length === 0 ? (
          <li className="dayOff-note">{t("Nothing on the calendar for kids nearby yet - ask schoolz for ideas.")}</li>
        ) : (
          picks.map((e, i) => (
            <li key={e.id}>
              <Link className="next-row" to={`/local?day=${plan.date}&event=${encodeURIComponent(e.id)}`} onClick={() => trackEvent("day_off_pick", { position: i + 1 })}>
                <span className="d">{untimed(e) ? t("All day") : timeOfDay(e.start_time)}</span>
                <span className="t">
                  {e.title}
                  <small>{[e.venue_name, e.miles != null && t("{{n}} mi", { n: e.miles })].filter(Boolean).join(" · ")}</small>
                </span>
                {e.is_free ? <span className="tag new">{t("Free")}</span> : <span />}
              </Link>
            </li>
          ))
        )}
        <li className="next-more">
          <Link to={`/local?day=${plan.date}`} onClick={() => trackEvent("day_off_all_events", { days_ahead: plan.daysAhead })}>
            {today ? t("All local events today") : t("All local events on {{day}}", { day: weekday })} <IconChevronRight className="trailing-chevron" />
          </Link>
        </li>
      </ul>
      <div className="actions">
        <button type="button" className="action primary" onClick={ask}>
          <IconMessage />
          {t("Ask schoolz what to do")}
        </button>
      </div>
    </section>
  );
}
