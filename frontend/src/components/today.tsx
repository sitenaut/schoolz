import { Link } from "react-router-dom";
import { googleCalendarQuickAddUrl, itemDateKeys, localDateKey, monthDay, shortDay, telHref, timeOfDay, todayKey } from "../lib/calendar";
import { isNoisyDistrictItem } from "../lib/districtItems";
import { useMySchools } from "../lib/mySchools";
import { schoolTypeLabel } from "../lib/schoolType";
import { trackEvent } from "../lib/track";
import type { CurrentPeriod, SchoolContentItem, SchoolToday, TodayContact, TodayDay } from "../types";
import { AbsenceButton } from "./AbsenceButton";
import { IconChevronRight, IconPhone } from "./icons";

/* ---------- small shared bits ---------- */

export function StatusPill({ status, label, hours }: { status: TodayDay["status"]; label: string | null; hours: string | null }) {
  if (status === "closed") return <span className="status bad">Closed{label ? ` · ${label}` : ""}</span>;
  if (status === "early_dismissal") return <span className="status warn">Early dismissal{hours ? ` · ${hours}` : ""}</span>;
  if (status === "delayed") return <span className="status warn">Delayed opening{hours ? ` · ${hours}` : ""}</span>;
  if (status === "weekend") return <span className="status muted">No school</span>;
  return <span className="status ok">Open{hours ? ` · ${hours}` : ""}</span>;
}

/** "Period 6 · ends 2:30 PM" - only rendered when the school has a real
 * bell_periods table and the request landed inside a named period (the
 * backend already returns null for gaps the table doesn't cover, before
 * the first period, after the last one, or on a non-school day). */
export function CurrentPeriodChip({ period }: { period: CurrentPeriod | null }) {
  if (!period) return null;
  const soon = period.minutes_left <= 5;
  return (
    <span className={`periodChip ${soon ? "periodChipSoon" : ""}`} title={`${period.minutes_in} min in, ${period.minutes_left} min left`}>
      Period {period.name} · {soon ? `ends in ${period.minutes_left} min` : `ends ${period.end_label}`}
    </span>
  );
}

export function ItemTag({ item }: { item: SchoolContentItem }) {
  if (item.category === "deadline") return <span className="tag deadline">due</span>;
  // Report card/interim/marking-period-end dates aren't something a
  // parent has to act on (no form to submit, nothing due) - "due" would
  // be misleading, so these get their own label instead.
  if (item.category === "marking_period") return <span className="tag grading">grading</span>;
  if (item.scope === "district") return <span className="tag district">district</span>;
  if (item.category === "policy_change" || item.category === "procedure") return <span className="tag new">updated</span>;
  return <span className="tag">{item.category.replace("_", " ")}</span>;
}

/** One dated item as a list row: big day number on the left, title +
 * description + links on the right. Used by school page + calendar. */
export function ItemRow({ item, color, schoolName, highlighted }: { item: SchoolContentItem; color?: string; schoolName?: string | null; highlighted?: boolean }) {
  const key = item.start_date ? localDateKey(item.start_date) : null;
  const md = key ? monthDay(key) : null;
  // A multi-day item (a closure spanning several days, most often) only
  // showed its first day here even after the calendar grid itself was
  // fixed to mark every day it covers - this list row is a separate
  // rendering path with the same "only ever looked at start_date" gap.
  const days = item.start_date ? itemDateKeys(item) : [];
  const lastKey = days.length > 1 ? days[days.length - 1] : null;
  const mdEnd = lastKey ? monthDay(lastKey) : null;
  const cal = item.start_date ? googleCalendarQuickAddUrl(item) : null;
  const timePart = item.start_date && !item.is_all_day ? timeOfDay(item.start_date) : null;
  return (
    <div className={`row${highlighted ? " rowHighlight" : ""}`} id={`event-${item.id}`}>
      <div className="when">
        {md ? (
          mdEnd ? (
            mdEnd.month === md.month ? (
              <>
                {md.month}
                <b>
                  {md.day}–{mdEnd.day}
                </b>
              </>
            ) : (
              <>
                {md.month}–{mdEnd.month}
                <b>
                  {md.day}–{mdEnd.day}
                </b>
              </>
            )
          ) : (
            <>
              {md.month}
              <b>{md.day}</b>
            </>
          )
        ) : (
          "—"
        )}
      </div>
      <div className="what">
        <div className="ttl">
          {color && <span className="sch" style={{ ["--c" as string]: color }} />}
          {item.title}
        </div>
        {timePart && <div className="desc">{timePart}</div>}
        {item.description && <div className="desc">{item.description}</div>}
        <div className="tagrow">
          {schoolName && (
            <span className="tag schoolTag" style={color ? { ["--c" as string]: color } : undefined}>
              {schoolName}
            </span>
          )}
          <ItemTag item={item} />
        </div>
        {(cal || item.link_url) && (
          <div className="links">
            {item.link_url && (
              <a href={item.link_url} target="_blank" rel="noreferrer">
                Open link
              </a>
            )}
            {cal && (
              <a href={cal} target="_blank" rel="noreferrer" onClick={() => trackEvent("action", { action: "add_to_calendar", method: "link" })}>
                Add to calendar
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function contactHref(c: TodayContact): { href: string; label: string } | null {
  if (c.email) return { href: `mailto:${c.email}`, label: c.email };
  if (c.phone) return { href: telHref(c.phone), label: c.phone };
  return null;
}

export function ContactGrid({ contacts, mainPhone }: { contacts: TodayContact[]; mainPhone: string | null }) {
  const hasOffice = contacts.some((c) => c.role === "secretary");
  return (
    <div className="contacts">
      {!hasOffice && mainPhone && (
        <div className="contact">
          <span className="role">Main office</span>
          <span className="name">Front desk</span>
          <a className="how" href={telHref(mainPhone)}>
            {mainPhone}
          </a>
        </div>
      )}
      {contacts.map((c) => {
        const h = contactHref(c);
        return (
          <div className="contact" key={c.role}>
            <span className="role">{c.label}</span>
            <span className="name">{c.name}</span>
            {h ? (
              <a className="how" href={h.href}>
                {h.label}
              </a>
            ) : (
              <span className="how muted">no contact listed</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- the Today-feed card ---------- */

export function DayCard({ data, color }: { data: SchoolToday; color: string }) {
  const { excludeDistrict } = useMySchools();
  const s = data.school;
  const kind = schoolTypeLabel(s.school_type);
  const nurse = data.contacts.find((c) => c.role === "nurse");
  const counselor = data.contacts.find((c) => c.role === "counselor");
  const nurseHref = nurse ? contactHref(nurse) : null;
  const counselorHref = counselor ? contactHref(counselor) : null;
  const sacc = data.sacc;
  const track = (action: string, method: string) => trackEvent("action", { action, method, school_slug: s.slug });
  // Same "exclude district" setting as the Calendar page - a parent who
  // hid board-of-ed-meeting-style noise there shouldn't see it resurface
  // here. Status items (closed/half day/delayed) and grading dates are
  // never filtered (see lib/districtItems.ts); day-rotation markers never
  // reach `upcoming` at all (backend/services/school_today.py excludes
  // them - that's the metadata line under the school name instead).
  const upcoming = (excludeDistrict ? data.upcoming.filter((i) => !isNoisyDistrictItem(i)) : data.upcoming).slice(0, 3);

  return (
    <section className="day" style={{ ["--c" as string]: color }}>
      <header>
        <div>
          <h2>
            <Link to={`/schools/${s.slug}`}>{s.short_name || s.name}</Link>
          </h2>
          <div className="kids">{[kind, data.rotation_day].filter(Boolean).join(" · ")}</div>
        </div>
        <div className="headerPills">
          <StatusPill status={data.status} label={data.status_label} hours={data.hours} />
          <CurrentPeriodChip period={data.current_period} />
        </div>
      </header>

      {(data.lunch.today || data.lunch.next || sacc) && (
        <div className="facts">
          {(data.lunch.today || data.lunch.next) && (
            <div className="fact">
              <div className="fact-head">
                <div className="k">{data.lunch.today ? "Lunch today" : "Next lunch"}</div>
                <Link className="fact-more" to={`/lunch?school=${s.slug}`}>
                  Lunch schedule <IconChevronRight className="trailing-chevron" />
                </Link>
              </div>
              <div className="v">{data.lunch.today ?? data.lunch.next}</div>
              {data.lunch.today && data.lunch.next && (
                <div className="sub">
                  {data.lunch.next_label}: {data.lunch.next}
                </div>
              )}
            </div>
          )}
          {sacc && (
            <div className="fact">
              <div className="k">After school</div>
              <div className="v">{sacc.pm_hours ? `SACC ${sacc.pm_hours.replace(/\s*-\s*/, "–")}` : "SACC"}</div>
              {sacc.site_phone && (
                <div className="sub">
                  Site: <a href={telHref(sacc.site_phone)}>{sacc.site_phone}</a>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {upcoming.length > 0 && (
        <ul className="next">
          {upcoming.map((i) => (
            <li key={i.id}>
              <span className="d">{shortDay(i.start_date!)}</span>
              <span className="t">
                {i.title}
                {!i.is_all_day && i.start_date && <small>{timeOfDay(i.start_date)}</small>}
              </span>
              <ItemTag item={i} />
            </li>
          ))}
          <li className="next-more">
            {/* Deep-links the calendar to just this school - district-wide
                dates come along automatically, the backend always includes
                a selected school's district. */}
            <Link to={`/calendar?school=${s.slug}`}>
              All dates for {s.short_name || s.name} <IconChevronRight className="trailing-chevron" />
            </Link>
          </li>
        </ul>
      )}

      <div className="actions">
        <AbsenceButton school={s} />
        {s.main_phone && (
          <a className="action" href={telHref(s.main_phone)} onClick={() => track("main_office", "tel")}>
            <IconPhone />
            Main office
          </a>
        )}
        {nurseHref && (
          <a className="action" href={nurseHref.href} onClick={() => track("nurse", "tel")}>
            Nurse
          </a>
        )}
        {counselorHref && (
          <a className="action" href={counselorHref.href} onClick={() => track("counselor", "tel")}>
            Counselor
          </a>
        )}
        {sacc?.site_phone && (
          <a className="action" href={telHref(sacc.site_phone)} onClick={() => track("sacc_late_line", "tel")}>
            Running late (SACC)
          </a>
        )}
        {data.transportation?.office_phone && (
          <a
            className="action"
            href={telHref(data.transportation.office_phone)}
            title="District transportation office"
            onClick={() => track("bus_office", "tel")}
          >
            <IconPhone />
            Bus office
          </a>
        )}
        {data.transportation?.late_bus_phone && (
          <a
            className="action"
            href={telHref(data.transportation.late_bus_phone)}
            title={`Late bus: ${data.transportation.late_bus_contractor}`}
            onClick={() => track("late_bus", "tel")}
          >
            Late bus
          </a>
        )}
        {s.athletics_url && (
          <a className="action" href={s.athletics_url} target="_blank" rel="noreferrer" onClick={() => track("sports", "link")}>
            Sports &amp; band
          </a>
        )}
        <Link className="action" to={`/schools/${s.slug}`}>
          Everything <IconChevronRight className="trailing-chevron" />
        </Link>
      </div>
    </section>
  );
}

/* ---------- week strip on the school page ---------- */

export function WeekStrip({ week, schoolSlug }: { week: TodayDay[]; schoolSlug: string }) {
  const { excludeDistrict } = useMySchools();
  const today = todayKey();
  return (
    <div className="week">
      {week.map((d) => {
        const md = monthDay(d.date);
        const cls = ["wd", d.date === today && "today", d.status === "closed" && "closed"].filter(Boolean).join(" ");
        const items = excludeDistrict ? d.items.filter((i) => !isNoisyDistrictItem(i)) : d.items;
        const dayHref = `/calendar?school=${schoolSlug}&date=${d.date}`;
        return (
          <div className={cls} key={d.date}>
            <div className="dn">{d.weekday}</div>
            <Link className="dd tab-num" to={dayHref}>
              {md.day}
            </Link>
            {d.rotation_day && <div className="rot">{d.rotation_day}</div>}
            {d.status === "closed" && <span className="pill bad">{d.status_label || "Closed"}</span>}
            {d.status === "early_dismissal" && <span className="pill warn">Early dismissal</span>}
            {d.status === "delayed" && <span className="pill warn">{d.status_label}</span>}
            {items.slice(0, 2).map((i) => (
              <Link className={`pill ${i.category === "deadline" ? "bad" : "ev"}`} to={`${dayHref}&event=${i.id}`} key={i.id} title={i.title}>
                {i.title}
              </Link>
            ))}
            {d.lunch && (
              <Link className="lunch" to={`/lunch?school=${schoolSlug}&date=${d.date}`}>
                {d.lunch}
              </Link>
            )}
          </div>
        );
      })}
    </div>
  );
}
