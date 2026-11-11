import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { AddChildForm, GuardianInvite, SpecialsEditor } from "../components/FamilyPanels";
import { IconChevronLeft, IconGradCap, IconPalette } from "../components/icons";
import { StudentLoginInvite } from "../components/StudentLoginInvite";
import { useAuth } from "../context/AuthContext";
import { IconChevronRight, IconCircleCheck, IconPeople, IconUser, TabIcon } from "../gradez/components/icons";
import { agoWords } from "../gradez/format";
import { freshness } from "../gradez/lib/freshness";
import type { GradezTab } from "../gradez/types";
import { fmtDateTime } from "../lib/format";
import { gradezHref } from "../lib/gradezPath";
import { ROUTER_BASENAME } from "../lib/i18n";
import {
  BACKPACK_CAPTURE_STORE_URL,
  awaitingSetup,
  bringsIn,
  districtSentences,
  gradeLevel,
  gradesLine,
  guardiansLine,
  hasSchoolwork,
  joinNames,
  latestSync,
  offersSchoolwork,
  scheduleLine,
  studentLoginLine,
  teachersLine,
  timeAgo,
  todoLine,
  updateLine,
  type FamilyChild,
  type LastUpdate,
} from "../lib/family";

type PanelKind = "guardian" | "student" | "specials";
type Panel = { childId: string; kind: PanelKind } | null;
type Loaded = { children: FamilyChild[]; at: number };

// Options for the grad-year picker - this year through 6 years out covers
// every currently-enrollable student (grad_year only means anything once a
// kid is at a high school, so a short, scannable list beats a long one).
function gradYearOptions(): number[] {
  const now = new Date();
  const start = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
  return Array.from({ length: 7 }, (_, i) => start + 1 + i);
}

/** My family: every child on this account, a way into each tab of their
 * Gradez page, and who else sees it. Replaced /children (a form and four
 * unexplained buttons) and the guardian's list of children that Gradez's
 * predecessor had. Schoolwork appears only for a child whose school has
 * Google Classroom or Genesis (GET /family decides, per district). */
export function FamilyPage() {
  const { user } = useAuth();
  const studentProfileId = user?.student_profile_id ?? null;
  const isStudent = Boolean(studentProfileId);
  const [data, setData] = useState<Loaded | null>(null);
  // Kept apart from an empty family: a guardian with children must never be
  // shown "Add your first child" because a deploy was under way.
  const [loadFailed, setLoadFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [panel, setPanel] = useState<Panel>(null);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<LastUpdate | null>(null);

  useEffect(() => {
    if (isStudent) return;
    let live = true;
    apiFetch("/family")
      .then((r) => {
        if (!r.ok) throw new Error(`family ${r.status}`);
        return r.json();
      })
      .then(
        (children: FamilyChild[]) => {
          if (!live) return;
          setData({ children, at: Date.now() });
          setLoadFailed(false);
        },
        () => {
          if (live) setLoadFailed(true);
        },
      );
    apiFetch("/capture-devices/last-update")
      .then((r) => (r.ok ? r.json() : null))
      .then((u: LastUpdate | null) => {
        if (live) setLastUpdate(u);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [isStudent, reload]);

  // A child's own login has one page, their own Gradez. A page load, not a
  // navigation: Gradez's document starts no analytics (lib/gradezPath.ts).
  useEffect(() => {
    if (studentProfileId) window.location.replace(ROUTER_BASENAME + gradezHref(studentProfileId));
  }, [studentProfileId]);

  if (isStudent) return null;

  const refresh = () => setReload((n) => n + 1);
  const retry = () => {
    setLoadFailed(false);
    refresh();
  };
  const toggle = (childId: string, kind: PanelKind) => {
    const closing = panel?.childId === childId && panel.kind === kind;
    setPanel(closing ? null : { childId, kind });
    if (closing) refresh();
  };
  const closePanel = () => {
    setPanel(null);
    refresh();
  };
  /** Resolves false when the removal didn't happen, so the card can say so:
   * a failed DELETE used to look the same as a removal that hadn't shown up
   * yet. Undefined when they changed their mind. */
  const remove = async (c: FamilyChild): Promise<boolean | undefined> => {
    if (!confirm(`Remove ${c.first_name} from your family? This only affects your own view.`)) return undefined;
    const r = await apiFetch(`/students/${c.id}`, { method: "DELETE" }).catch(() => null);
    if (r?.ok) refresh();
    return Boolean(r?.ok);
  };
  /** Shown at once, put back if the save fails. Resolves to whether it saved. */
  const setGradYear = async (c: FamilyChild, gradYear: number | null): Promise<boolean> => {
    const swap = (from: number | null, to: number | null) =>
      setData((d) => d && { ...d, children: d.children.map((k) => (k.id === c.id && k.grad_year === from ? { ...k, grad_year: to } : k)) });
    swap(c.grad_year, gradYear);
    const r = await apiFetch(`/students/${c.id}`, { method: "PATCH", body: JSON.stringify({ grad_year: gradYear }) }).catch(() => null);
    if (r?.ok) return true;
    swap(gradYear, c.grad_year);
    return false;
  };
  const added = (msg: string | null) => {
    setAdding(false);
    setNotice(msg);
    refresh();
  };

  const children = data?.children ?? [];

  return (
    <div className="page page-narrow fam">
      <Link to="/" className="back-link">
        <IconChevronLeft /> Home
      </Link>
      <h1>My family</h1>
      <p className="fam-intro">
        {children.some(hasSchoolwork)
          ? "Each row opens the matching tab of your child's page."
          : "What schoolz does for each of your kids. Only you and the guardians you share a child with see this page."}
      </p>

      {notice && <div className="banner">{notice}</div>}

      {data !== null && loadFailed && (
        <div className="banner bad">
          <span>Couldn't update this page just now.</span>
          <button type="button" className="btn sm" onClick={retry}>
            Try again
          </button>
        </div>
      )}

      {data === null ? (
        loadFailed ? (
          <div className="card">
            <p className="fam-report-error">Couldn't load your family just now.</p>
            <button type="button" className="btn" onClick={retry}>
              Try again
            </button>
          </div>
        ) : (
          <p className="note">Loading…</p>
        )
      ) : children.length === 0 ? (
        <div className="card">
          <h2 className="fam-h2">Add your first child</h2>
          <p className="note">Were you sent an invite link? Open it and the child appears here on its own.</p>
          <AddChildForm onAdded={added} />
        </div>
      ) : (
        <>
          <SchoolworkCard kids={children} now={data.at} update={lastUpdate} />
          {children.map((c) => (
            <ChildCard
              key={c.id}
              child={c}
              now={data.at}
              open={panel?.childId === c.id ? panel.kind : null}
              onToggle={(kind) => toggle(c.id, kind)}
              onClosePanel={closePanel}
              onRemove={() => remove(c)}
              onGradYear={(y) => setGradYear(c, y)}
            />
          ))}
          {adding ? (
            <div className="card">
              <h2 className="fam-h2">Add a child</h2>
              <AddChildForm onAdded={added} onCancel={() => setAdding(false)} />
            </div>
          ) : (
            <button type="button" className="btn fam-add" onClick={() => setAdding(true)}>
              + Add a child
            </button>
          )}
        </>
      )}
    </div>
  );
}

const GENESIS_FOR_NOW = (
  <>
    Update now reads Google Classroom. For Genesis grades and schedule, for now: in Backpack Capture press <strong>More</strong> →{" "}
    <strong>Start capture</strong>, open the Genesis pages, then <strong>Send to schoolz</strong>.
  </>
);

/** The one card about getting homework and grades in: the full steps until
 * Backpack Capture has sent anything, then a status line - plus, for a child
 * still waiting once it's running, how to add them to the same setup. */
function SchoolworkCard({ kids, now, update }: { kids: FamilyChild[]; now: number; update: LastUpdate | null }) {
  const waiting = awaitingSetup(kids);
  const last = latestSync(kids);
  const names = joinNames(waiting.map((c) => c.first_name));
  const genesis = waiting.some((c) => c.has_genesis);

  if (!last && waiting.length > 0) {
    return (
      <div className="card fam-setup">
        <div className="eyebrow">Homework and grades</div>
        <h2>Bring {names}'s schoolwork into schoolz</h2>
        <p>
          {districtSentences(waiting).join(" ")} Connect once on a computer, and schoolz brings in {bringsIn(waiting)}, updated every few
          hours.
        </p>
        <ol className="fam-steps">
          <li>
            <span>Add Backpack Capture to Chrome</span>
          </li>
          <li>
            <span>
              Press <strong>Connect to schoolz</strong>
            </span>
          </li>
          <li>
            <span>
              Press <strong>Update now</strong>
            </span>
          </li>
        </ol>
        <div className="fam-cta">
          <a className="btn btn-primary" href={BACKPACK_CAPTURE_STORE_URL} target="_blank" rel="noopener noreferrer">
            Get Backpack Capture
          </a>
          <Link className="more" to="/backpack-capture/privacy">
            What it reads, and what it doesn't
          </Link>
        </div>
        {genesis && <p className="fam-aside">{GENESIS_FOR_NOW}</p>}
        <p className="fam-aside">
          You never type a school password into schoolz. Once it's in, ask the chat things like{" "}
          <em>"What is {waiting[0].first_name} missing this week?"</em>
        </p>
        {update && <UpdateStatus update={update} />}
      </div>
    );
  }
  if (!last)
    return update ? (
      <div className="card fam-sync">
        <UpdateStatus update={update} />
      </div>
    ) : null;

  // Backpack Capture already runs for someone in the family: a waiting child
  // needs their own school account in that Chrome, not a second install.
  // How current each child's schoolwork is sits under their card, and the
  // full account (with Report a problem) is Gradez's About this data, so a
  // card here is only for an update that ran into trouble a parent must fix.
  const classroomWaiting = waiting.filter((c) => c.has_classroom);
  return (
    <>
      {update?.summary?.outcome === "trouble" && (
        <div className="card fam-sync">
          <div className="fam-sync-hd">
            <span>
              <span className="dot warn" aria-hidden="true" />
              <b>Backpack Capture</b> last sent schoolwork {timeAgo(last, now)} <span className="when">({fmtDateTime(last)})</span>
            </span>
            <Link to="/account/security">Connected computers</Link>
          </div>
          <UpdateStatus update={update} />
        </div>
      )}
      {waiting.length > 0 && (
        <div className="card fam-setup">
          <div className="eyebrow">Homework and grades</div>
          <h2>Nothing from {names} yet</h2>
          {classroomWaiting.length > 0 && (
            <p>
              Sign {joinNames(classroomWaiting.map((c) => c.first_name))}'s school Google account in to the Chrome that runs Backpack Capture,
              then press <strong>Update now</strong>. It finds the account by itself.
            </p>
          )}
          {genesis && <p className={classroomWaiting.length > 0 ? "fam-aside" : undefined}>{GENESIS_FOR_NOW}</p>}
        </div>
      )}
    </>
  );
}

/** The last update as Backpack Capture summed it up, the problems that
 * need a parent's attention (the extension decides which do), and the way
 * to tell schoolz when something still looks wrong. */
function UpdateStatus({ update }: { update: LastUpdate }) {
  const problems = update.summary?.outcome === "trouble" ? update.summary.problems : [];
  return (
    <div className="fam-update">
      <p>{updateLine(update, fmtDateTime)}</p>
      {problems.length > 0 && (
        <ul className="fam-problems">
          {problems.map((p, i) => (
            <li key={i}>{p.text}</li>
          ))}
        </ul>
      )}
      <ReportProblem update={update} />
    </div>
  );
}

/** Report a problem: a message to the schoolz team's Inbox, tied to the
 * update's log so whoever helps can see what it did. */
function ReportProblem({ update }: { update: LastUpdate | null }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<{ reference: string | null } | null>(
    update?.reported_at ? { reference: update.reference } : null,
  );
  const [error, setError] = useState<string | null>(null);

  if (sent) {
    return (
      <p className="fam-report-sent">
        Reported to the schoolz team{sent.reference ? `, reference ${sent.reference}` : ""}. They'll reply by email.
      </p>
    );
  }
  if (!open) {
    return (
      <button type="button" className="btn sm fam-report" onClick={() => setOpen(true)}>
        Report a problem
      </button>
    );
  }
  const send = async () => {
    setSending(true);
    setError(null);
    const r = await apiFetch("/capture-devices/report", {
      method: "POST",
      body: JSON.stringify({ note: note.trim() || null, diagnostic_id: update?.id ?? null }),
    }).catch(() => null);
    setSending(false);
    if (r?.ok) setSent(await r.json());
    else setError(r?.status === 429 ? "That's several reports in the last hour. Try again later." : "Couldn't send that. Try again in a minute.");
  };
  return (
    <div className="fam-report-form">
      <label htmlFor="fam-report-note">What went wrong? (optional)</label>
      <textarea
        id="fam-report-note"
        rows={3}
        maxLength={2000}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="For example: it kept asking me to sign in"
      />
      <p className="note">
        {update
          ? "The schoolz team also gets this update's log: which pages it opened and where it stopped, never what was on them."
          : "The schoolz team gets your message and your account's email address."}
      </p>
      {error && <p className="fam-report-error">{error}</p>}
      <div className="fam-cta">
        <button type="button" className="btn btn-primary sm" onClick={send} disabled={sending}>
          {sending ? "Sending…" : "Send to schoolz"}
        </button>
        <button type="button" className="btn sm" onClick={() => setOpen(false)} disabled={sending}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** One row of a child's card: an icon, a title, a line of status under
 * it, and what the row does at the end. */
function RowBody({ icon, title, status, warn, end }: { icon: ReactNode; title: string; status?: string | null; warn?: boolean; end?: ReactNode }) {
  return (
    <>
      <span className="fam-row-ico">{icon}</span>
      <span className="fam-row-text">
        <span className="fam-row-title">{title}</span>
        {status && <span className={`fam-row-status${warn ? " warn" : ""}`}>{status}</span>}
      </span>
      {end}
    </>
  );
}

const TAB_ROWS: { tab: GradezTab; title: string }[] = [
  { tab: "todo", title: "To do" },
  { tab: "grades", title: "Grades" },
  { tab: "schedule", title: "Schedule" },
  { tab: "teachers", title: "Teachers" },
];

function ChildCard({
  child: c,
  now,
  open,
  onToggle,
  onClosePanel,
  onRemove,
  onGradYear,
}: {
  child: FamilyChild;
  now: number;
  open: PanelKind | null;
  onToggle: (kind: PanelKind) => void;
  onClosePanel: () => void;
  onRemove: () => Promise<boolean | undefined>;
  onGradYear: (year: number | null) => Promise<boolean>;
}) {
  const offers = offersSchoolwork(c);
  const captured = hasSchoolwork(c);
  const [gradYearFailed, setGradYearFailed] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeFailed, setRemoveFailed] = useState(false);

  const name = `${c.first_name} ${c.last_name}`.trim();
  const grade = gradeLevel(c, new Date(now));
  const sub = [grade != null ? `Grade ${grade}` : null, c.school_name].filter(Boolean).join(" · ");
  // Gradez is reached by a page load, never a router navigation: its
  // document starts no analytics (lib/gradezPath.ts).
  const href = (tab: GradezTab, extra?: Record<string, string>) => ROUTER_BASENAME + gradezHref(c.id, tab, extra);
  const grades = gradesLine(c);
  const status: Record<GradezTab, string | null> = {
    todo: todoLine(c),
    grades: grades?.text ?? null,
    schedule: scheduleLine(c),
    teachers: teachersLine(c),
  };
  const panelButton = (kind: PanelKind, label: string, ariaLabel: string) => (
    <button type="button" className="fam-row-btn" onClick={() => onToggle(kind)} aria-expanded={open === kind} aria-label={ariaLabel}>
      {label}
    </button>
  );
  const panel = (kind: PanelKind, body: ReactNode) => open === kind && <div className="fam-panel">{body}</div>;

  return (
    <div className="fam-child">
      <section className="card fam-kid" aria-label={name}>
        <div className="fam-kid-hd">
          <span className="fam-avatar" aria-hidden="true">
            {c.first_name.slice(0, 1)}
          </span>
          <div className="who">
            <h2>{name}</h2>
            {sub && <div className="sub">{sub}</div>}
          </div>
          <a className="fam-open" href={href("todo")}>
            Open
          </a>
        </div>

        {captured &&
          TAB_ROWS.map((r) => (
            <a key={r.tab} className="fam-row fam-tab-row" href={href(r.tab)}>
              <RowBody
                icon={<TabIcon tab={r.tab} />}
                title={r.title}
                status={status[r.tab]}
                warn={r.tab === "grades" && Boolean(grades?.low)}
                end={<IconChevronRight />}
              />
            </a>
          ))}
        {offers && !captured && <p className="fam-none">{c.first_name}'s schoolwork shows up here once Backpack Capture has sent it.</p>}
        {!offers && <p className="fam-none">Homework and grades aren't available{c.school_name ? ` at ${c.school_name}` : ""} yet.</p>}

        <h3 className="fam-h3">People</h3>
        {offers && (
          <>
            <div className="fam-row">
              <RowBody
                icon={<IconUser />}
                title={`${c.first_name}'s own login`}
                status={studentLoginLine(c)}
                end={panelButton(
                  "student",
                  c.student_login_email || c.student_invite_email ? "Manage" : "Invite",
                  c.student_login_email || c.student_invite_email ? `Manage ${c.first_name}'s own login` : `Invite ${c.first_name} to their own login`,
                )}
              />
            </div>
            {panel("student", <StudentLoginInvite studentId={c.id} firstName={c.first_name} />)}
          </>
        )}
        <button type="button" className="fam-row fam-row-toggle" onClick={() => onToggle("guardian")} aria-expanded={open === "guardian"}>
          <RowBody icon={<IconPeople />} title="Guardians" status={guardiansLine(c)} end={<IconChevronRight />} />
        </button>
        {panel("guardian", <GuardianInvite student={c} onClose={onClosePanel} />)}

        {(c.school_type === "elementary" || c.school_type === "high") && <h3 className="fam-h3">Settings</h3>}
        {c.school_type === "elementary" && (
          <>
            <div className="fam-row">
              <RowBody
                icon={<IconPalette />}
                title="Specials"
                status={
                  c.specials_count
                    ? `${c.specials_count} day${c.specials_count === 1 ? "" : "s"} filled in, shown on your Today page`
                    : "Art, PE or Music on the right day, on your Today page"
                }
                end={panelButton("specials", c.specials_count ? "Edit" : "Add", c.specials_count ? `Edit ${c.first_name}'s specials` : `Add ${c.first_name}'s specials`)}
              />
            </div>
            {panel("specials", <SpecialsEditor student={c} onClose={onClosePanel} />)}
          </>
        )}
        {c.school_type === "high" && (
          <div className="fam-row">
            <RowBody
              icon={<IconGradCap />}
              title="Graduating class"
              status={`Class events for ${c.first_name}'s year on the school page`}
              end={
                <select
                  value={c.grad_year ?? ""}
                  onChange={(e) => {
                    setGradYearFailed(false);
                    void onGradYear(e.target.value ? Number(e.target.value) : null).then((ok) => setGradYearFailed(!ok));
                  }}
                  aria-label={`${c.first_name}'s graduating class`}
                >
                  <option value="">Not set</option>
                  {gradYearOptions().map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              }
            />
          </div>
        )}
        {gradYearFailed && <p className="fam-report-error fam-card-error">Couldn't save the graduating class. Try again in a minute.</p>}

        <div className="fam-foot">
          <span>Student ID {c.student_id}</span>
          <button
            type="button"
            disabled={removing}
            onClick={async () => {
              setRemoving(true);
              const ok = await onRemove();
              setRemoving(false);
              setRemoveFailed(ok === false);
            }}
          >
            Remove from my family
          </button>
        </div>
        {removeFailed && <p className="fam-report-error fam-card-error">Couldn't remove {c.first_name} just now. Try again in a minute.</p>}
      </section>
      {captured && <DataLink child={c} now={now} href={href("todo", { sheet: "data" })} />}
    </div>
  );
}

/** How current the child's schoolwork is, opening Gradez's About this data.
 * Green only when Gradez's own header would say so too. */
function DataLink({ child: c, now, href }: { child: FamilyChild; now: number; href: string }) {
  const fresh = freshness({ classroom_seen_at: c.classroom_seen_at, genesis_seen_at: c.genesis_seen_at, walk_status: null, walk_finished_at: null, needs_login: c.needs_login }, now);
  if (!fresh || fresh.kind === "never") return null;
  const tone = c.needs_login ? "warn" : fresh.kind === "stale" ? "stale" : "ok";
  return (
    <a className={`fam-data fam-data-${tone}`} href={href}>
      {tone === "ok" && <IconCircleCheck />}
      {c.needs_login ? "Google Classroom asked to sign in again" : `Schoolwork updated ${agoWords(fresh.ago)}`}
    </a>
  );
}
