import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiFetch } from "../api";
import { AbsenceButton } from "../components/AbsenceButton";
import { ContactGrid, CurrentPeriodChip, ItemRow, StatusPill, WeekStrip, contactHref } from "../components/today";
import { IconChevronLeft } from "../components/icons";
import { localDateKey, telHref, todayKey } from "../lib/calendar";
import { schoolTypeLabel } from "../lib/schoolType";
import { trackEvent, trackMeasurement } from "../lib/track";
import type { SaccProgram, SchoolContentItem, SchoolDocument, SchoolToday, SchoolTransportation, StaffMember } from "../types";

type Newsletter = { id: string; label: string | null; url: string; latest_summary: string | null; last_scanned_at: string | null };

const MORE_SECTIONS: { category: string; title: string }[] = [
  { category: "program", title: "Programs" },
  { category: "org_club", title: "Clubs & organizations" },
  { category: "volunteer", title: "Volunteering" },
  { category: "busing", title: "Busing & arrival" },
  { category: "funding", title: "Funding & contributions" },
  { category: "policy_change", title: "Policy updates" },
  { category: "procedure", title: "Procedures" },
  { category: "merch_ad", title: "Spirit wear & local ads" },
  { category: "initiative", title: "Initiatives" },
];

function currentAcademicYear(): string {
  const d = new Date();
  const y = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1;
  return `${y}-${y + 1}`;
}

export function SchoolDetailPage() {
  const { schoolId } = useParams<{ schoolId: string }>();
  const [today, setToday] = useState<SchoolToday | null>(null);
  const [items, setItems] = useState<SchoolContentItem[]>([]);
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [documents, setDocuments] = useState<SchoolDocument[]>([]);
  const [sacc, setSacc] = useState<SaccProgram | null>(null);
  const [newsletters, setNewsletters] = useState<Newsletter[]>([]);
  const [transport, setTransport] = useState<SchoolTransportation | null>(null);
  const [missing, setMissing] = useState(false);
  const readyStart = useRef(performance.now());

  useEffect(() => {
    if (!schoolId) return;
    readyStart.current = performance.now();
    Promise.all([
      apiFetch(`/schools/${schoolId}/today`).then((r) => (r.ok ? r.json() : null)),
      apiFetch(`/schools/${schoolId}/content`).then((r) => (r.ok ? r.json() : [])),
      apiFetch(`/schools/${schoolId}/staff`).then((r) => (r.ok ? r.json() : [])),
      apiFetch(`/schools/${schoolId}/documents`).then((r) => (r.ok ? r.json() : [])),
      apiFetch(`/schools/${schoolId}/sacc`).then((r) => (r.ok ? r.json() : null)),
      apiFetch(`/schools/${schoolId}/newsletters`).then((r) => (r.ok ? r.json() : [])),
      apiFetch(`/schools/${schoolId}/transportation`).then((r) => (r.ok ? r.json() : null)),
    ]).then(([t, c, st, docs, sc, nl, tr]) => {
      if (!t) setMissing(true);
      setToday(t);
      setItems(c);
      setStaff(st);
      setDocuments(docs);
      setSacc(sc);
      setNewsletters(nl);
      setTransport(tr);
      if (t) trackMeasurement("school_page_ready", performance.now() - readyStart.current, { school_slug: schoolId! });
    });
  }, [schoolId]);

  const tk = todayKey();
  const upcoming = useMemo(
    () =>
      items
        .filter((i) => ["event", "deadline", "initiative", "marking_period"].includes(i.category) && i.start_date && localDateKey(i.start_date) >= tk && !/^Day \d$/.test(i.title))
        .sort((a, b) => (a.start_date! < b.start_date! ? -1 : 1))
        .slice(0, 12),
    [items, tk],
  );
  const reminders = items.filter((i) => i.category === "reminder");
  const pta = items.filter((i) => i.category === "pta");
  const people = items.filter((i) => i.category === "person");
  const summary = newsletters.find((n) => n.latest_summary)?.latest_summary;
  const newsletterUrl = newsletters[0]?.url;

  if (missing) return <div className="empty">School not found.</div>;
  if (!today) return <p className="note">Loading…</p>;
  const s = today.school;
  const nurse = today.contacts.find((c) => c.role === "nurse");
  const counselor = today.contacts.find((c) => c.role === "counselor");
  const thisYear = currentAcademicYear();
  const track = (action: string, method: string) => trackEvent("action", { action, method, school_slug: s.slug });

  return (
    <>
      <Link to="/" className="back-link">
        <IconChevronLeft /> Today
      </Link>
      <div className="school-hd">
        <div className="eyebrow">{[schoolTypeLabel(s.school_type), "Cherry Hill Public Schools"].filter(Boolean).join(" · ")}</div>
        <h1>{s.name}</h1>
        <div className="meta">
          {s.address && (
            <a href={`https://maps.google.com/?q=${encodeURIComponent(s.address)}`} target="_blank" rel="noreferrer">
              {s.address}
            </a>
          )}
          {s.main_phone && <a href={telHref(s.main_phone)}>{s.main_phone}</a>}
          {s.website_url && (
            <a href={s.website_url} target="_blank" rel="noreferrer">
              Website
            </a>
          )}
          {newsletterUrl && (
            <a href={newsletterUrl} target="_blank" rel="noreferrer">
              Newsletter
            </a>
          )}
          {s.athletics_url && (
            <a href={s.athletics_url} target="_blank" rel="noreferrer">
              Sports &amp; band schedule
            </a>
          )}
        </div>
        <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <StatusPill status={today.status} label={today.status_label} hours={today.hours} />
          <CurrentPeriodChip period={today.current_period} />
          {today.rotation_day && <span className="note">{today.rotation_day} today</span>}
        </div>
        {s.start_time && s.end_time && (
          <p className="note" style={{ marginTop: 6 }}>
            Regular day {s.start_time}–{s.end_time}
            {s.early_dismissal_time && ` · early dismissal ends ${s.early_dismissal_time}`}
            {s.delayed_opening_time && ` · delayed opening starts ${s.delayed_opening_time}`}
          </p>
        )}
      </div>

      <div className="sticky-actions">
        <div className="actions bare">
          <AbsenceButton school={s} />
          {nurse && contactHref(nurse) && (
            <a className="action" href={contactHref(nurse)!.href} onClick={() => track("nurse", "tel")}>
              Nurse
            </a>
          )}
          {counselor && contactHref(counselor) && (
            <a className="action" href={contactHref(counselor)!.href} onClick={() => track("counselor", "tel")}>
              Counselor
            </a>
          )}
          {today.sacc?.site_phone && (
            <a className="action" href={telHref(today.sacc.site_phone)} onClick={() => track("sacc_late_line", "tel")}>
              SACC late line
            </a>
          )}
          {s.main_phone && (
            <a className="action" href={telHref(s.main_phone)} onClick={() => track("main_office", "tel")}>
              Main office
            </a>
          )}
          {transport?.district.office_phone && (
            <a
              className="action"
              href={telHref(transport.district.office_phone)}
              title="District transportation office"
              onClick={() => track("bus_office", "tel")}
            >
              Bus office
            </a>
          )}
          {s.athletics_url && (
            <a className="action" href={s.athletics_url} target="_blank" rel="noreferrer" onClick={() => track("sports", "link")}>
              Sports &amp; band
            </a>
          )}
        </div>
      </div>
      {s.absence_instructions && s.absence_method !== "portal" && <p className="note">{s.absence_instructions}</p>}

      <div className="h-row">
        <h2>This week</h2>
        <Link to={`/calendar?school=${s.slug}`}>Full calendar</Link>
      </div>
      <WeekStrip week={today.week} />
      {today.lunch.source_pdf_url && (
        <p className="note" style={{ marginTop: 8 }}>
          Lunch from the district's{" "}
          <a href={today.lunch.source_pdf_url} target="_blank" rel="noreferrer">
            monthly menu
          </a>
          . <Link to="/lunch">Whole month</Link>
        </p>
      )}

      {reminders.length > 0 && (
        <>
          <div className="h-row">
            <h2>Reminders</h2>
          </div>
          <div className="list">
            {reminders.map((i) => (
              <ItemRow item={i} key={i.id} />
            ))}
          </div>
        </>
      )}

      <div className="h-row">
        <h2>Coming up</h2>
        <Link to={`/calendar?school=${s.slug}`}>All dates</Link>
      </div>
      {upcoming.length === 0 ? (
        <div className="empty">Nothing dated yet. Check back after the next newsletter.</div>
      ) : (
        <div className="list">
          {upcoming.map((i) => (
            <ItemRow item={i} key={i.id} />
          ))}
        </div>
      )}

      {pta.length > 0 && (
        <>
          <div className="h-row">
            <h2>PTA</h2>
          </div>
          <div className="list">
            {pta.map((i) => (
              <ItemRow item={i} key={i.id} />
            ))}
          </div>
        </>
      )}

      <div className="h-row">
        <h2>Who to contact</h2>
      </div>
      <ContactGrid contacts={today.contacts} mainPhone={s.main_phone} />
      {staff.length > 0 && (
        <details className="acc" style={{ marginTop: 8 }}>
          <summary>Full staff directory ({staff.length})</summary>
          <div className="body people-grid">
            {staff.map((m) => (
              <div className="person-card" key={m.id}>
                <div className="person-name">{m.full_name}</div>
                {m.title && <div className="person-title">{m.title}</div>}
                {m.email && (
                  <div className="person-title">
                    <a href={`mailto:${m.email}`}>{m.email}</a>
                  </div>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {sacc && (
        <>
          <div className="h-row">
            <h2>After-school care (SACC)</h2>
          </div>
          <div className="sacc">
            <div className="hours">
              {sacc.am_hours && (
                <div>
                  <b>AM</b>
                  {sacc.am_hours}
                </div>
              )}
              {sacc.pm_hours && (
                <div>
                  <b>PM</b>
                  {sacc.pm_hours}
                </div>
              )}
              {sacc.site_phone && (
                <div>
                  <b>Site phone</b>
                  <a href={telHref(sacc.site_phone)}>{sacc.site_phone}</a>
                </div>
              )}
            </div>
            <ul className="qa">
              <li>
                <b>Kid won't be at PM SACC today?</b>
                <span>Report it by 3:00 PM. Telling the teacher or school office does not count - SACC doesn't cross-check.</span>{" "}
                {sacc.absence_form_url && (
                  <a href={sacc.absence_form_url} target="_blank" rel="noreferrer">
                    Report a PM absence
                  </a>
                )}
                {sacc.absence_phone && (
                  <>
                    {" "}
                    · <a href={telHref(sacc.absence_phone)}>SACC office {sacc.absence_phone}</a>
                  </>
                )}
              </li>
              {sacc.pickup_change_procedure && (
                <li>
                  <b>Someone else picking up?</b>
                  <span>{sacc.pickup_change_procedure}</span>
                </li>
              )}
              {sacc.late_pickup_policy && (
                <li>
                  <b>Running late?</b>
                  <span>{sacc.late_pickup_policy}</span>
                </li>
              )}
              {sacc.closures_notes && (
                <li>
                  <b>Delays & early dismissals</b>
                  <span>{sacc.closures_notes}</span>
                </li>
              )}
              {sacc.handbook_url && (
                <li>
                  <a href={sacc.handbook_url} target="_blank" rel="noreferrer">
                    SACC Family Handbook
                  </a>
                </li>
              )}
            </ul>
          </div>
        </>
      )}

      {transport && (
        <>
          <div className="h-row">
            <h2>Buses &amp; transportation</h2>
            {transport.district.main_url && (
              <a href={transport.district.main_url} target="_blank" rel="noreferrer">
                District page
              </a>
            )}
          </div>
          <div className="sacc">
            <div className="hours">
              {transport.district.office_phone && (
                <div>
                  <b>Transportation office</b>
                  <a href={telHref(transport.district.office_phone)}>{transport.district.office_phone}</a>
                </div>
              )}
              {transport.district.office_hours && (
                <div>
                  <b>Hours</b>
                  {transport.district.office_hours}
                </div>
              )}
              {transport.late_bus && (
                <div>
                  <b>Late bus</b>
                  <a href={telHref(transport.late_bus.phone)}>{transport.late_bus.phone}</a>
                </div>
              )}
            </div>
            <ul className="qa">
              <li>
                <b>Bus running late?</b>
                <span>
                  Call the transportation office{transport.district.office_hours ? ` (${transport.district.office_hours})` : ""}.
                  {transport.district.delay_policy ? ` ${transport.district.delay_policy}` : ""}
                </span>
              </li>
              <li>
                <b>Late bus after activities</b>
                {transport.late_bus ? (
                  <span>
                    {transport.late_bus.contractor} runs this school's late buses (routes {transport.late_bus.routes.join(", ")}). Ask the school secretary which route your child is
                    on. {transport.district.late_bus_policy}
                  </span>
                ) : (
                  <span>Late buses only run for the middle and high schools; there is no late bus at this school.</span>
                )}
              </li>
              {transport.district.bus_stop_change_procedure && (
                <li>
                  <b>Need a different stop for today?</b>
                  <span>{transport.district.bus_stop_change_procedure}</span>
                </li>
              )}
              {(transport.district.bus_stop_change_deadline || transport.district.bus_stop_change_form_url) && (
                <li>
                  <b>Changing your regular bus stop</b>
                  {transport.district.bus_stop_change_deadline && <span>{transport.district.bus_stop_change_deadline}</span>}{" "}
                  {transport.district.bus_stop_change_form_url && (
                    <a href={transport.district.bus_stop_change_form_url} target="_blank" rel="noreferrer">
                      Bus stop change request form
                    </a>
                  )}
                </li>
              )}
              {transport.district.lost_items_policy && (
                <li>
                  <b>Left something on the bus?</b>
                  <span>{transport.district.lost_items_policy}</span>{" "}
                  {transport.district.lost_items_url && (
                    <a href={transport.district.lost_items_url} target="_blank" rel="noreferrer">
                      Lost items
                    </a>
                  )}
                </li>
              )}
              {transport.district.closing_info_url && (
                <li>
                  <b>Weather closings &amp; delays</b>
                  <a href={transport.district.closing_info_url} target="_blank" rel="noreferrer">
                    School closing information
                  </a>
                </li>
              )}
            </ul>
            {transport.district.contacts.length > 0 && (
              <details className="acc" style={{ marginTop: 10 }}>
                <summary>Transportation department staff ({transport.district.contacts.length})</summary>
                <div className="body people-grid">
                  {transport.district.contacts.map((c) => (
                    <div className="person-card" key={c.email ?? c.name}>
                      <div className="person-name">{c.name}</div>
                      <div className="person-title">{c.title}</div>
                      {c.email && (
                        <div className="person-title">
                          <a href={`mailto:${c.email}`}>{c.email}</a>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                {transport.district.office_address && <p className="note" style={{ margin: "8px 14px 0" }}>{transport.district.office_address}</p>}
              </details>
            )}
          </div>
        </>
      )}

      {documents.length > 0 && (
        <>
          <div className="h-row">
            <h2>Documents</h2>
          </div>
          <div className="list docs">
            {documents.map((d) => {
              const stale = Boolean(d.academic_year && d.academic_year !== thisYear);
              return (
                <a
                  href={d.url}
                  target="_blank"
                  rel="noreferrer"
                  className={stale ? "stale" : ""}
                  key={d.id}
                  onClick={() => trackEvent("action", { action: "document_open", method: "link", school_slug: s.slug })}
                >
                  📄 {d.doc_type === "bell_schedule" ? "Bell schedule" : d.title}
                  <small>{d.academic_year ? (stale ? `${d.academic_year} · may be outdated` : d.academic_year) : d.source}</small>
                </a>
              );
            })}
          </div>
        </>
      )}

      {(summary || people.length > 0 || MORE_SECTIONS.some((m) => items.some((i) => i.category === m.category))) && (
        <div className="h-row">
          <h2>More from the newsletter</h2>
        </div>
      )}
      {summary && (
        <details className="acc">
          <summary>Latest newsletter summary</summary>
          <div className="body">{summary}</div>
        </details>
      )}
      {MORE_SECTIONS.map(({ category, title }) => {
        const sectionItems = items.filter((i) => i.category === category);
        if (sectionItems.length === 0) return null;
        return (
          <details className="acc" key={category}>
            <summary>
              {title} ({sectionItems.length})
            </summary>
            <div className="body">
              <div className="list" style={{ boxShadow: "none", border: "1px solid var(--line)" }}>
                {sectionItems.map((i) => (
                  <ItemRow item={i} key={i.id} />
                ))}
              </div>
            </div>
          </details>
        );
      })}
      {people.length > 0 && (
        <details className="acc">
          <summary>People mentioned ({people.length})</summary>
          <div className="body people-grid">
            {people.map((p) => {
              const matched = staff.find((m) => m.id === p.staff_member_id);
              return (
                <div className="person-card" key={p.id}>
                  <div className="person-name">{p.person_name || p.title}</div>
                  {(matched?.title || p.person_title) && <div className="person-title">{matched?.title || p.person_title}</div>}
                  {matched?.email && (
                    <div className="person-title">
                      <a href={`mailto:${matched.email}`}>{matched.email}</a>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </details>
      )}
      <p className="fine">Pulled from the school's newsletter and website, and the district calendar.</p>
    </>
  );
}
