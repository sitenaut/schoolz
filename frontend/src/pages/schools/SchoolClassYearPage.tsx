import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiFetch } from "../../api";
import { ItemRow } from "../../components/today";
import { IconChevronLeft } from "../../components/icons";
import { SeoHead } from "../../components/SeoHead";
import { useAuth } from "../../context/AuthContext";
import { localDateKey, monthDay, schoolCalendarPath, todayKey } from "../../lib/calendar";
import { usePrerenderReady } from "../../lib/prerenderReady";
import { useViewerEpoch } from "../../lib/viewer";
import type { ClassPayment, School, SchoolClassYear, SchoolContentItem } from "../../types";
import { LOCALE } from "../../lib/i18n";

type StudentMini = { id: string; school_id: string | null; grad_year: number | null };

function formatCents(cents: number | null): string {
  if (cents === null) return "TBD";
  return `$${(cents / 100).toLocaleString(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatWindow(opensAt: string | null, closesAt: string | null): string | null {
  if (!closesAt) return opensAt ? `opens ${monthDay(localDateKey(opensAt)).month} ${monthDay(localDateKey(opensAt)).day}` : null;
  const md = monthDay(localDateKey(closesAt));
  return `due ${md.month} ${md.day}`;
}

function PaymentRow({ payment, onToggle, busy }: { payment: ClassPayment; onToggle: (p: ClassPayment) => void; busy: boolean }) {
  const closed = payment.window_closes_at ? new Date(payment.window_closes_at).getTime() < Date.now() : false;
  const window = formatWindow(payment.window_opens_at, payment.window_closes_at);
  return (
    <div className="row">
      <div className="when" style={{ minWidth: 28 }}>
        {payment.ticked !== null ? (
          <input
            type="checkbox"
            checked={!!payment.ticked}
            disabled={busy}
            onChange={() => onToggle(payment)}
            aria-label={`Mark ${payment.label} paid`}
          />
        ) : (
          <span aria-hidden="true">{closed ? "✓" : "○"}</span>
        )}
      </div>
      <div className="what">
        <div className="ttl" style={{ textDecoration: closed && !payment.ticked ? "line-through" : "none" }}>
          {payment.label} — {formatCents(payment.amount_cents)}
        </div>
        {(window || payment.payschools_item_name) && <div className="desc">{[window, payment.payschools_item_name].filter(Boolean).join(" · ")}</div>}
        {payment.notes && <div className="desc">{payment.notes}</div>}
      </div>
    </div>
  );
}

export function SchoolClassYearPage() {
  const { schoolId, classSlug } = useParams<{ schoolId: string; classSlug: string }>();
  // "class-of-2027" -> "2027" - see the route comment in App.tsx for why
  // this is parsed here instead of matched as ":gradYear" in the route.
  const gradYearParam = classSlug?.match(/^class-of-(\d{4})$/)?.[1];
  const gradYear = Number(gradYearParam);
  const { user } = useAuth();
  // Ticks are the viewer's own, so the payments are read again on sign-in
  // and sign-out; they used to load only once, at mount.
  const viewerEpoch = useViewerEpoch();

  const [school, setSchool] = useState<School | null>(null);
  const [classYears, setClassYears] = useState<SchoolClassYear[]>([]);
  const [items, setItems] = useState<SchoolContentItem[]>([]);
  const [payments, setPayments] = useState<ClassPayment[]>([]);
  const [myStudents, setMyStudents] = useState<StudentMini[]>([]);
  const [missing, setMissing] = useState(false);
  // Which class the data on screen is for. The class-of tabs change the URL
  // in place, and the previous class's items stayed up under the new
  // heading until the new ones arrived.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const loaded = loadedFor === `${schoolId}/${gradYearParam}`;
  // Payment ticks with a save in flight: a second tap on one gave a 500.
  const [ticking, setTicking] = useState<ReadonlySet<string>>(new Set());
  // The server didn't answer, which says nothing about whether the school or
  // its class page exists. Bumping `attempt` reads again.
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!schoolId || !gradYearParam) return;
    let current = true;
    const loading = `${schoolId}/${gradYearParam}`;
    // A 404 is an answer (no such school, or no page for that year); any
    // other failure rejects, so the page offers Try again instead.
    const read = <T,>(path: string, notFound: T): Promise<T> =>
      apiFetch(path).then((r) => {
        if (r.status === 404) return notFound;
        if (!r.ok) throw new Error(`${path} ${r.status}`);
        return r.json();
      });
    Promise.all([
      read<School | null>(`/schools/${schoolId}`, null),
      read<SchoolClassYear[]>(`/schools/${schoolId}/class-years`, []),
      read<SchoolContentItem[]>(`/schools/${schoolId}/class-years/${gradYearParam}/content`, []),
      read<ClassPayment[]>(`/schools/${schoolId}/class-years/${gradYearParam}/payments`, []),
    ]).then(
      ([s, cy, c, p]) => {
        if (!current) return;
        setFailed(false);
        setMissing(!s);
        setSchool(s);
        setClassYears(cy);
        setItems(c);
        setPayments(p);
        setLoadedFor(loading);
      },
      () => {
        if (current) setFailed(true);
      },
    );
    return () => {
      current = false;
    };
  }, [schoolId, gradYearParam, attempt, viewerEpoch]);
  // Without it the prerender waited out its timeout on every class page and
  // stored nothing: Googlebot got a 5xx (Search Console listed them) and,
  // once nginx fell back to the bare app, 25s of nothing per page. Not on
  // `failed`: that render would replace the stored snapshot with the error.
  usePrerenderReady(loaded || !gradYearParam);

  useEffect(() => {
    if (!user) return;
    apiFetch("/students")
      .then((r) => (r.ok ? r.json() : []))
      .catch(() => [])
      .then(setMyStudents);
  }, [user]);

  const thisClassYear = classYears.find((c) => c.grad_year === gradYear);
  const currentClass = useMemo(
    () => Boolean(user) && myStudents.some((s) => s.school_id === school?.id && s.grad_year === gradYear),
    [user, myStudents, school, gradYear],
  );

  const { events, eventsTotal, deadlines, more } = useMemo(() => {
    const allEvents: SchoolContentItem[] = [];
    const deadlines: SchoolContentItem[] = [];
    const more: SchoolContentItem[] = [];
    for (const i of items) {
      if (i.category === "event") allEvents.push(i);
      else if (i.category === "deadline") deadlines.push(i);
      else more.push(i);
    }
    const byDate = (a: SchoolContentItem, b: SchoolContentItem) => (a.start_date ?? "") < (b.start_date ?? "") ? -1 : 1;
    const sortedEvents = allEvents.sort(byDate);
    // A class page's own activities calendar/announcements run to dozens
    // of club meetings a week (the whole reason they're absorbed here
    // instead of the general calendar - see docs/HS_CLASS_PAGES_DESIGN.md)
    // - capped the same way SchoolDetailPage's own "Coming up" is, rather
    // than dumping every event on file into one unbounded list.
    const today = todayKey();
    const upcoming = sortedEvents.filter((i) => !i.start_date || localDateKey(i.start_date) >= today).slice(0, 30);
    return { events: upcoming, eventsTotal: sortedEvents.length, deadlines: deadlines.sort(byDate), more };
  }, [items]);

  // "Next up": the earliest thing that still protects something by acting
  // now - an un-ticked payment whose window hasn't closed, before any
  // ordinary dated item. Same rationale as the Focus tab's own
  // prioritization (see CLAUDE.md's late-work-policies notes).
  const nextPayment = useMemo(
    () => payments.find((p) => !p.ticked && (!p.window_closes_at || new Date(p.window_closes_at).getTime() >= Date.now())),
    [payments],
  );
  const today = todayKey();
  const nextDeadline = deadlines.find((d) => !d.start_date || localDateKey(d.start_date) >= today);

  const togglePayment = async (payment: ClassPayment) => {
    if (ticking.has(payment.id)) return;
    setTicking((cur) => new Set(cur).add(payment.id));
    setPayments((cur) => cur.map((p) => (p.id === payment.id ? { ...p, ticked: !p.ticked } : p)));
    try {
      const res = await apiFetch(`/schools/${schoolId}/class-years/${gradYearParam}/payments/${payment.id}/tick`, { method: "POST" });
      if (!res.ok) throw new Error(`tick ${res.status}`);
      const updated: ClassPayment = await res.json();
      setPayments((cur) => cur.map((p) => (p.id === payment.id ? updated : p)));
    } catch {
      // Not saved: show it the way it still is.
      setPayments((cur) => cur.map((p) => (p.id === payment.id ? { ...p, ticked: payment.ticked } : p)));
    } finally {
      setTicking((cur) => {
        const next = new Set(cur);
        next.delete(payment.id);
        return next;
      });
    }
  };

  if (!gradYearParam) {
    return (
      <div>
        <Link to={schoolId ? `/schools/${schoolId}` : "/schools"} className="back-link">
          <IconChevronLeft /> School
        </Link>
        <div className="empty">Not a class page - class URLs look like ".../class-of-2027".</div>
      </div>
    );
  }
  if (failed) {
    return (
      <div>
        <Link to={`/schools/${schoolId}`} className="back-link">
          <IconChevronLeft /> School
        </Link>
        <div className="empty">
          <p>Couldn't load this class page just now.</p>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
  if (loaded && missing) {
    return (
      <div>
        <Link to="/schools" className="back-link">
          <IconChevronLeft /> Schools
        </Link>
        <div className="empty">This school couldn't be found.</div>
      </div>
    );
  }
  if (loaded && school && !thisClassYear) {
    // A class this school has no page for used to sit on "Loading…" forever.
    return (
      <div>
        <Link to={`/schools/${schoolId}`} className="back-link">
          <IconChevronLeft /> {school.short_name || school.name}
        </Link>
        <div className="empty">No Class of {gradYear} page for {school.short_name || school.name}.</div>
      </div>
    );
  }
  if (!loaded || !school || !thisClassYear) return <p>Loading…</p>;

  // The trip's real total is what the "official" windows sum to (the
  // amount a family owes if they pay nothing optionally in advance) - NOT
  // a sum of every row's face amount. Confirmed real on East's own site:
  // its FAQ states a flat "$2,275.00" total cost, which equals exactly
  // its three official deposits ($750+$750+$775) and nothing more - the
  // four optional deposits are early installments CREDITED toward that
  // same total, not additional charges on top of it. Summing all seven
  // face amounts (as an earlier version of this page did) double-counts
  // an optional prepayment and whatever portion of the official schedule
  // it was later credited against, overstating the trip by exactly
  // however much was paid optionally - a real, live error caught by
  // checking this page's numbers against the school's own stated total
  // rather than trusting the arithmetic. paidCents still sums every
  // ticked window (optional or official) - real money sent counts toward
  // the total regardless of which window it went through.
  const totalCents = payments.filter((p) => p.kind === "official").reduce((sum, p) => (p.amount_cents ? sum + p.amount_cents : sum), 0);
  const paidCents = payments.reduce((sum, p) => (p.ticked && p.amount_cents ? sum + p.amount_cents : sum), 0);

  return (
    <div>
      <SeoHead
        title={`Class of ${gradYear} · ${school.short_name || school.name} · schoolz`}
        description={`Deadlines, dates, and payment info for the Class of ${gradYear} at ${school.short_name || school.name}.`}
        path={`/schools/${school.slug}/class-of-${gradYear}`}
      />
      <Link to={`/schools/${school.slug}`} className="back-link">
        <IconChevronLeft /> {school.short_name || school.name}
      </Link>

      <div className="school-hd">
        <div className="eyebrow">{[thisClassYear.label, school.short_name || school.name].filter(Boolean).join(" · ")}</div>
        <h1>Class of {gradYear}</h1>
        {currentClass && <span className="note">This is your child's class.</span>}
      </div>

      {classYears.length > 1 && (
        <div className="tabs" style={{ margin: "8px 0 20px" }}>
          {classYears.map((c) => (
            <Link key={c.grad_year} className={`tab ${c.grad_year === gradYear ? "active" : ""}`} to={`/schools/${school.slug}/class-of-${c.grad_year}`}>
              {c.grad_year}
            </Link>
          ))}
        </div>
      )}

      {(nextPayment || nextDeadline) && (
        <>
          <div className="h-row">
            <h2>Next for this class</h2>
          </div>
          <div className="list">
            {nextPayment && <PaymentRow payment={nextPayment} onToggle={togglePayment} busy={ticking.has(nextPayment.id)} />}
            {!nextPayment && nextDeadline && <ItemRow item={nextDeadline} />}
          </div>
        </>
      )}

      {payments.length > 0 && (
        <>
          <div className="h-row">
            <h2>Money &amp; deadlines</h2>
            {totalCents > 0 && (
              <span className="note">
                {formatCents(paidCents)} of {formatCents(totalCents)}
              </span>
            )}
          </div>
          <div className="list">
            {payments.map((p) => (
              <PaymentRow payment={p} onToggle={togglePayment} busy={ticking.has(p.id)} key={p.id} />
            ))}
          </div>
        </>
      )}

      <div className="h-row">
        <h2>Dates for this class</h2>
        <Link to={schoolCalendarPath(school.slug)}>Full calendar</Link>
      </div>
      {events.length === 0 ? (
        <div className="empty">Nothing dated yet for this class.</div>
      ) : (
        <>
          <div className="list">
            {events.map((i) => (
              <ItemRow item={i} key={i.id} />
            ))}
          </div>
          {eventsTotal > events.length && (
            <p className="note">
              Showing the next {events.length} of {eventsTotal}. <Link to={schoolCalendarPath(school.slug)}>See the rest</Link>
            </p>
          )}
        </>
      )}

      {deadlines.length > 0 && (
        <>
          <div className="h-row">
            <h2>Deadlines</h2>
          </div>
          <div className="list">
            {deadlines.map((i) => (
              <ItemRow item={i} key={i.id} />
            ))}
          </div>
        </>
      )}

      <div className="h-row">
        <h2>Who to ask</h2>
      </div>
      <div className="people-grid">
        {thisClassYear.grade_level_principals.map((p) => (
          <div className="person-card" key={p.id}>
            <div className="person-name">{p.full_name}</div>
            <div className="person-title">Grade level principal</div>
            {p.email && (
              <div className="person-title">
                <a href={`mailto:${p.email}`}>{p.email}</a>
              </div>
            )}
          </div>
        ))}
        {thisClassYear.advisors.map((a) => (
          <div className="person-card" key={a.id}>
            <div className="person-name">{a.full_name}</div>
            <div className="person-title">Class advisor</div>
            {a.email && (
              <div className="person-title">
                <a href={`mailto:${a.email}`}>{a.email}</a>
              </div>
            )}
          </div>
        ))}
        {thisClassYear.grade_level_principals.length === 0 && thisClassYear.advisors.length === 0 && (
          <div className="empty">No contacts on file yet for this class.</div>
        )}
      </div>

      {thisClassYear.instagram_url && (
        <p className="note" style={{ marginTop: 12 }}>
          <a href={thisClassYear.instagram_url} target="_blank" rel="noreferrer">
            Class of {gradYear} on Instagram
          </a>
        </p>
      )}

      {more.length > 0 && (
        <details className="acc" style={{ marginTop: 28 }}>
          <summary>More for this class ({more.length})</summary>
          <div className="body">
            <div className="list">
              {more.map((i) => (
                <ItemRow item={i} key={i.id} />
              ))}
            </div>
          </div>
        </details>
      )}

      {thisClassYear.source_page_url && (
        <p className="note" style={{ marginTop: 16 }}>
          Source:{" "}
          <a href={thisClassYear.source_page_url} target="_blank" rel="noreferrer">
            the school's own activities site
          </a>
        </p>
      )}
    </div>
  );
}
