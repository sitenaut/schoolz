import { Link } from "react-router-dom";
import { googleCalendarQuickAddUrl, localDateKey, monthDay, shortDay, telHref, timeOfDay, todayKey } from "../lib/calendar";
import { schoolTypeLabel } from "../lib/schoolType";
import type { CurrentPeriod, SchoolContentItem, SchoolToday, TodayContact, TodayDay } from "../types";
import { AbsenceButton } from "./AbsenceButton";
import { IconPhone } from "./icons";

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
  if (item.scope === "district") return <span className="tag district">district</span>;
  if (item.category === "policy_change" || item.category === "procedure") return <span className="tag new">updated</span>;
  return <span className="tag">{item.category.replace("_", " ")}</span>;
}

/** One dated item as a list row: big day number on the left, title +
 * description + links on the right. Used by school page + calendar. */
export function ItemRow({ item, color, schoolName }: { item: SchoolContentItem; color?: string; schoolName?: string | null }) {
  const key = item.start_date ? localDateKey(item.start_date) : null;
  const md = key ? monthDay(key) : null;
  const cal = item.start_date ? googleCalendarQuickAddUrl(item) : null;
  const sub = [schoolName, item.start_date && !item.is_all_day ? timeOfDay(item.start_date) : null].filter(Boolean).join(" · ");
  return (
    <div className="row">
      <div className="when">
        {md ? (
          <>
            {md.month}
            <b>{md.day}</b>
          </>
        ) : (
          "—"
        )}
      </div>
      <div className="what">
        <div className="ttl">
          {color && <span className="sch" style={{ ["--c" as string]: color }} />}
          {item.title}
        </div>
        {sub && <div className="desc">{sub}</div>}
        {item.description && <div className="desc">{item.description}</div>}
        <div className="tagrow">
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
              <a href={cal} target="_blank" rel="noreferrer">
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
  const s = data.school;
  const kind = schoolTypeLabel(s.school_type);
  const nurse = data.contacts.find((c) => c.role === "nurse");
  const counselor = data.contacts.find((c) => c.role === "counselor");
  const nurseHref = nurse ? contactHref(nurse) : null;
  const counselorHref = counselor ? contactHref(counselor) : null;
  const sacc = data.sacc;

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
                <Link className="fact-more" to="/lunch">
                  Lunch schedule ›
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

      {data.upcoming.length > 0 && (
        <ul className="next">
          {data.upcoming.slice(0, 3).map((i) => (
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
            <Link to={`/calendar?school=${s.slug}`}>All dates for {s.short_name || s.name} ›</Link>
          </li>
        </ul>
      )}

      <div className="actions">
        <AbsenceButton school={s} />
        {s.main_phone && (
          <a className="action" href={telHref(s.main_phone)}>
            <IconPhone />
            Main office
          </a>
        )}
        {nurseHref && (
          <a className="action" href={nurseHref.href}>
            Nurse
          </a>
        )}
        {counselorHref && (
          <a className="action" href={counselorHref.href}>
            Counselor
          </a>
        )}
        {sacc?.site_phone && (
          <a className="action" href={telHref(sacc.site_phone)}>
            Running late (SACC)
          </a>
        )}
        {data.transportation?.office_phone && (
          <a className="action" href={telHref(data.transportation.office_phone)} title="District transportation office">
            <IconPhone />
            Bus office
          </a>
        )}
        {data.transportation?.late_bus_phone && (
          <a className="action" href={telHref(data.transportation.late_bus_phone)} title={`Late bus: ${data.transportation.late_bus_contractor}`}>
            Late bus
          </a>
        )}
        {s.athletics_url && (
          <a className="action" href={s.athletics_url} target="_blank" rel="noreferrer">
            Sports &amp; band
          </a>
        )}
        <Link className="action" to={`/schools/${s.slug}`}>
          Everything →
        </Link>
      </div>
    </section>
  );
}

/* ---------- week strip on the school page ---------- */

export function WeekStrip({ week }: { week: TodayDay[] }) {
  const today = todayKey();
  return (
    <div className="week">
      {week.map((d) => {
        const md = monthDay(d.date);
        const cls = ["wd", d.date === today && "today", d.status === "closed" && "closed"].filter(Boolean).join(" ");
        return (
          <div className={cls} key={d.date}>
            <div className="dn">{d.weekday}</div>
            <div className="dd tab-num">{md.day}</div>
            {d.rotation_day && <div className="rot">{d.rotation_day}</div>}
            {d.status === "closed" && <span className="pill bad">{d.status_label || "Closed"}</span>}
            {d.status === "early_dismissal" && <span className="pill warn">Early dismissal</span>}
            {d.status === "delayed" && <span className="pill warn">{d.status_label}</span>}
            {d.items.slice(0, 2).map((i) => (
              <span className={`pill ${i.category === "deadline" ? "bad" : "ev"}`} key={i.id} title={i.title}>
                {i.title}
              </span>
            ))}
            {d.lunch && <div className="lunch">{d.lunch}</div>}
          </div>
        );
      })}
    </div>
  );
}
