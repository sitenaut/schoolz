import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiFetch } from "../api";
import { SeoHead } from "../components/SeoHead";
import { localDateKey, monthDay, todayKey } from "../lib/calendar";
import { schoolTypeLabel } from "../lib/schoolType";
import { useMySchools } from "../lib/mySchools";
import { townsLabel } from "../lib/towns";
import { usePrerenderReady } from "../lib/prerenderReady";
import { trackMeasurement } from "../lib/track";
import type { LunchMenu, School } from "../types";
import { useTranslation } from "react-i18next";
import { LOCALE } from "../lib/i18n";

export function LunchPage() {
  const { t } = useTranslation();
  const { mySchools, activeSchools, loading, colorFor, myTowns } = useMySchools();
  const [params] = useSearchParams();
  // "Lunch schedule" links from a specific school's Today card / school
  // page (?school=slug) must land on THAT school, not always the ribbon's
  // first active one - previously every such link landed on the same
  // school regardless of which card's button was clicked, since nothing
  // told this page which one to pick.
  //
  // It lands there whether or not that school is one of yours: a visitor
  // with nothing picked (a new parent on a shared school page, every
  // crawler) used to be sent to the picker, and one with other schools
  // picked got their own first school's menu instead. 185 such links were
  // Search Console "Page with redirect"s.
  const deepSchool = params.get("school");
  // A "this week" meal tap (school page) carries which day to land on -
  // otherwise this page defaults to today, same as before.
  const deepDate = params.get("date");
  const [active, setActive] = useState<string | null>(deepSchool);
  const [menu, setMenu] = useState<LunchMenu | null | undefined>(undefined);
  // The linked school's name and type, when it isn't one of yours; null
  // once it turns out not to exist, so the page falls back to yours.
  const [fetchedDeep, setFetchedDeep] = useState<School | null | undefined>(undefined);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const readyStart = useRef(performance.now());
  const readyReported = useRef(false);

  useEffect(() => {
    // Keep the selected tab valid - picks the first active school once
    // data is ready if nothing (or a no-longer-tracked school) is selected
    // yet. A deep-linked school stays selected even if the ribbon filter
    // hides it or it isn't one of yours - explicit navigation wins.
    if (deepSchool && active === deepSchool && fetchedDeep !== null) return;
    if (activeSchools.length === 0) return;
    if (!active || !mySchools.some((s) => s.slug === active)) {
      setActive(activeSchools[0].slug);
    }
  }, [activeSchools, mySchools, active, deepSchool, fetchedDeep]);

  useEffect(() => {
    if (!deepSchool || loading || mySchools.some((s) => s.slug === deepSchool)) return;
    apiFetch(`/schools/${deepSchool}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setFetchedDeep);
  }, [deepSchool, loading, mySchools]);
  const deepObj = deepSchool ? (mySchools.find((s) => s.slug === deepSchool) ?? (fetchedDeep?.slug === deepSchool ? fetchedDeep : null)) : null;
  // The linked school leads the tabs when it isn't among the ones shown,
  // and its tab names it even when it's the only one - with nothing else
  // on the page saying whose menu this is.
  const deepIsExtra = !!deepObj && !activeSchools.some((s) => s.id === deepObj.id);
  const tabs = deepObj && deepIsExtra ? [deepObj, ...activeSchools] : activeSchools;

  useEffect(() => {
    if (!active) return;
    setMenu(undefined);
    apiFetch(`/schools/${active}/lunch-menu`)
      .then((r) => (r.ok ? r.json() : null))
      .then((m: LunchMenu | null) => {
        setMenu(m);
        if (!readyReported.current) {
          readyReported.current = true;
          trackMeasurement("lunch_ready", performance.now() - readyStart.current);
        }
      });
  }, [active]);

  const tk = todayKey();
  const items = menu?.items ?? [];

  // Every day in the month is listed (not just upcoming ones), scrolled
  // to whichever row is today - or the nearest day after it, if today
  // itself has no entry (a weekend, a break) - so today lands as the
  // first visible row without hiding the rest of the month above it. A
  // deep-linked date (from a school page's "this week" strip) takes
  // today's place as the scroll target.
  const targetDate = deepDate ?? tk;
  useEffect(() => {
    if (!scrollRef.current || items.length === 0) return;
    const onOrAfterTarget = items.find((i) => localDateKey(i.menu_date) >= targetDate);
    const targetKey = onOrAfterTarget ? localDateKey(onOrAfterTarget.menu_date) : null;
    const el = targetKey ? rowRefs.current.get(targetKey) : null;
    const container = scrollRef.current;
    if (el) {
      container.scrollTop = el.offsetTop - container.offsetTop;
    } else {
      container.scrollTop = 0;
    }
  }, [items, targetDate]);

  const school = tabs.find((s) => s.slug === active);

  const rows = useMemo(
    () =>
      items.map((i) => {
        const key = localDateKey(i.menu_date);
        const md = monthDay(key);
        const wd = new Date(key + "T12:00:00Z").toLocaleDateString(LOCALE, { weekday: "short", timeZone: "UTC" });
        return { item: i, key, md, wd, isToday: key === tk, isTarget: key === targetDate, isPast: key < tk };
      }),
    [items, tk, targetDate],
  );

  // Every listed day is behind us: the next menu hasn't been posted. Showing
  // the old month's list read as this month's (Burlington City showed
  // September all through October), so say so and link where it'll appear.
  const lastKey = rows.length > 0 ? rows[rows.length - 1].key : null;
  const isOver = !!lastKey && lastKey < tk;
  const monthName = (key: string) => new Date(key.slice(0, 7) + "-15T12:00:00Z").toLocaleDateString(LOCALE, { month: "long", timeZone: "UTC" });
  const shortDate = (key: string) => new Date(key + "T12:00:00Z").toLocaleDateString(LOCALE, { month: "short", day: "numeric", timeZone: "UTC" });
  const nextMenuUrl = menu?.source_page_url ?? (menu && !menu.source_pdf_url.startsWith("newsletter:") ? menu.source_pdf_url : null);

  // Nothing picked and no school in the link: ask for one in place, as
  // Today and Calendar do, rather than redirecting to the picker.
  const noSchools = !deepSchool && !loading && mySchools.length === 0;
  usePrerenderReady(menu !== undefined || noSchools);

  const seo = (
    <SeoHead
      title={t("Lunch menus · {{towns}} · schoolz", { towns: townsLabel(myTowns) })}
      description={t("Daily lunch menus for {{towns}} public schools, by school - synced from district and school-published menus.", { towns: townsLabel(myTowns) })}
      path="/lunch"
    />
  );

  if (noSchools)
    return (
      <>
        {seo}
        <h2 style={{ marginTop: 0 }}>{t("Lunch")}</h2>
        <div className="empty">
          <p>
            <strong>{t("Pick your kids' schools")}</strong> {t("to see their lunch menus here.")}
          </p>
          <p>
            <Link to="/start?next=/lunch" className="btn btn-primary attention">
              {t("Pick your schools")}
            </Link>
          </p>
        </div>
      </>
    );
  // A deep link can show its school's menu before we know whose schools
  // these are; anything else waits for that.
  if (loading && !deepSchool) return <p className="note">{t("Loading…")}</p>;

  return (
    <>
      {seo}
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>{t("Lunch")}</h2>
        {menu && !isOver && !menu.source_pdf_url.startsWith("newsletter:") && (
          <a href={menu.source_pdf_url} target="_blank" rel="noreferrer">
            {t("{{period}} PDF", { period: menu.period_label })}
          </a>
        )}
      </div>
      {(tabs.length > 1 || deepIsExtra) && (
        <div className="chips">
          {tabs.map((s) => (
            <button className="chip" aria-pressed={s.slug === active} style={{ ["--c" as string]: colorFor(s.id) }} onClick={() => setActive(s.slug)} key={s.id}>
              <span className="dot" />
              {s.short_name || s.name}
            </button>
          ))}
        </div>
      )}
      {menu === undefined ? (
        <p className="note">{t("Loading…")}</p>
      ) : menu === null ? (
        <div className="empty">{t("No lunch menu on file for {{school}} yet.", { school: school?.short_name || school?.name || active })}</div>
      ) : rows.length === 0 ? (
        <div className="empty">{t("No days listed for {{period}} yet.", { period: menu.period_label })}</div>
      ) : isOver && lastKey ? (
        <div className="empty">
          <p>
            <strong>
              {lastKey.slice(0, 7) < tk.slice(0, 7)
                ? t("{{month}}'s lunch menu hasn't been posted yet.", { month: monthName(tk) })
                : t("No lunch menu has been posted after {{date}} yet.", { date: shortDate(lastKey) })}
            </strong>
          </p>
          {nextMenuUrl && (
            <p>
              <a href={nextMenuUrl} target="_blank" rel="noreferrer">
                {menu.source_page_url ? t("Check the district's menu page") : t("Check the source")}
              </a>
            </p>
          )}
        </div>
      ) : (
        <>
          {/* tabIndex: a scrolling region has to be reachable from the keyboard (WCAG 2.1.1). */}
          <div className="list scrollList" ref={scrollRef} tabIndex={0} role="region" aria-label={t("Lunch menu")}>
            {rows.map(({ item, key, md, wd, isToday, isTarget, isPast }) => (
              <div
                className={`row ${isToday || isTarget ? "rowToday" : ""}`}
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
                  {isToday && <span className="todayBadge">{t("Today")}</span>}
                </div>
                <div className="what">
                  <div className="ttl">{item.description}</div>
                  {item.notes && <div className="desc">{item.notes}</div>}
                </div>
              </div>
            ))}
          </div>
          <p className="note" style={{ marginTop: 8 }}>
            {menu.period_label} · {schoolTypeLabel(school?.school_type ?? null) ? t("{{type}} menu", { type: schoolTypeLabel(school?.school_type ?? null) }) : t("school menu")} · {t("every day of the month, scrolled to today.")}
          </p>
        </>
      )}
      <p className="fine">
        {t("Something look off?")} <Link to={`/schools/${active}`}>{t("Open the school page")}</Link>.
      </p>
    </>
  );
}
