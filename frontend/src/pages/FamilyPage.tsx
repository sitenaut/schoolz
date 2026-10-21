import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { apiFetch } from "../api";
import { AddChildForm, GuardianInvite, SpecialsEditor } from "../components/FamilyPanels";
import { IconBook, IconChart, IconChevronLeft, IconClock, IconDevice, IconGradCap, IconPalette, IconUsers } from "../components/icons";
import { StudentLoginInvite } from "../components/StudentLoginInvite";
import { useAuth } from "../context/AuthContext";
import {
  BACKPACK_CAPTURE_STORE_URL,
  awaitingSetup,
  bringsIn,
  districtSentences,
  gradesLine,
  guardiansLine,
  hasSchoolwork,
  homeworkLine,
  joinNames,
  latestSync,
  offersSchoolwork,
  scheduleLine,
  systemsLabel,
  timeAgo,
  type FamilyChild,
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

/** My family: every child on this account, what schoolz can do for each,
 * what's switched on, and the one button that switches the rest on. Replaced
 * /children (a form and four unexplained buttons) and the /kids list.
 * Homework and grades appear only for a child whose school has Google
 * Classroom or Genesis (GET /family decides, per district). */
export function FamilyPage() {
  const { user } = useAuth();
  const isStudent = Boolean(user?.student_profile_id);
  const [data, setData] = useState<Loaded | null>(null);
  const [reload, setReload] = useState(0);
  const [panel, setPanel] = useState<Panel>(null);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (isStudent) return;
    let live = true;
    apiFetch("/family")
      .then((r) => (r.ok ? r.json() : []))
      .then((children: FamilyChild[]) => {
        if (live) setData({ children, at: Date.now() });
      });
    return () => {
      live = false;
    };
  }, [isStudent, reload]);

  if (isStudent) return <Navigate to={`/kids/${user!.student_profile_id}`} replace />;

  const refresh = () => setReload((n) => n + 1);
  const toggle = (childId: string, kind: PanelKind) => {
    const closing = panel?.childId === childId && panel.kind === kind;
    setPanel(closing ? null : { childId, kind });
    if (closing) refresh();
  };
  const closePanel = () => {
    setPanel(null);
    refresh();
  };
  const remove = async (c: FamilyChild) => {
    if (!confirm(`Remove ${c.first_name} from your family? This only affects your own view.`)) return;
    await apiFetch(`/students/${c.id}`, { method: "DELETE" });
    refresh();
  };
  const setGradYear = async (c: FamilyChild, gradYear: number | null) => {
    setData((d) => d && { ...d, children: d.children.map((k) => (k.id === c.id ? { ...k, grad_year: gradYear } : k)) });
    await apiFetch(`/students/${c.id}`, { method: "PATCH", body: JSON.stringify({ grad_year: gradYear }) });
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
      <p className="note fam-intro">
        What schoolz does for each of your kids. Only you and the guardians you share a child with see this page.
      </p>

      {notice && <div className="banner">{notice}</div>}

      {data === null ? (
        <p className="note">Loading…</p>
      ) : children.length === 0 ? (
        <div className="card">
          <h2 className="fam-h2">Add your first child</h2>
          <p className="note">Were you sent an invite link? Open it and the child appears here on its own.</p>
          <AddChildForm onAdded={added} />
        </div>
      ) : (
        <>
          <SchoolworkCard kids={children} now={data.at} />
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
function SchoolworkCard({ kids, now }: { kids: FamilyChild[]; now: number }) {
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
      </div>
    );
  }
  if (!last) return null;

  // Backpack Capture already runs for someone in the family: a waiting child
  // needs their own school account in that Chrome, not a second install.
  const classroomWaiting = waiting.filter((c) => c.has_classroom);
  return (
    <>
      <div className="card fam-sync">
        <span>
          <span className="dot" aria-hidden="true" />
          <b>Backpack Capture</b> last sent schoolwork {timeAgo(last, now)}
        </span>
        <Link to="/account/security">Connected computers</Link>
      </div>
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

function Row({
  icon,
  title,
  desc,
  src,
  on,
  warn,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  desc: React.ReactNode;
  src?: string;
  on?: boolean;
  warn?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <li className={`fam-row${on ? " on" : ""}${warn ? " warn" : ""}`}>
      <span className="fam-ico">{icon}</span>
      <span>
        <b>{title}</b>
        <small>{desc}</small>
        {src && <span className="src">{src}</span>}
      </span>
      <span className="fam-state">{children}</span>
    </li>
  );
}

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
  onRemove: () => void;
  onGradYear: (year: number | null) => void;
}) {
  const offers = offersSchoolwork(c);
  const seen = (iso: string | null) => (iso ? timeAgo(iso, now) : "Not yet");
  const panelBtn = (kind: PanelKind, label: string) => (
    <button type="button" className={`btn sm${open === kind ? " btn-primary" : ""}`} onClick={() => onToggle(kind)} aria-expanded={open === kind}>
      {label}
    </button>
  );
  const login = c.student_login_email ?? c.student_invite_email;

  return (
    <div className="card fam-kid">
      <div className="fam-kid-hd">
        <span className="fam-avatar" aria-hidden="true">
          {c.first_name.slice(0, 1)}
        </span>
        <div className="who">
          <h2>
            {c.first_name} {c.last_name}
          </h2>
          {c.school_name && <div className="sub">{c.school_name}</div>}
        </div>
        {hasSchoolwork(c) && (
          // Gradez is its own app at /focus/, not a route here - a plain link.
          <a className="btn sm btn-primary" href={`/focus/?student=${encodeURIComponent(c.id)}`} title={`Open ${c.first_name} in Gradez`}>
            Open
          </a>
        )}
      </div>

      {offers && (
        <div className="fam-group">
          <div className="eyebrow">From {systemsLabel(c.has_classroom, c.has_genesis)}</div>
          <ul className="fam-rows">
            {c.has_classroom && (
              <Row
                icon={<IconBook />}
                title="Homework"
                desc={c.needs_login ? "Google asked to sign in again. Sign in, then press Update now in Backpack Capture." : homeworkLine(c)}
                src="Google Classroom"
                on={Boolean(c.classroom_seen_at) && !c.needs_login}
                warn={c.needs_login}
              >
                {c.needs_login ? "Sign in again" : seen(c.classroom_seen_at)}
              </Row>
            )}
            {c.has_genesis && (
              <Row icon={<IconChart />} title="Grades" desc={gradesLine(c)} src="Genesis" on={Boolean(c.genesis_seen_at)}>
                {seen(c.genesis_seen_at)}
              </Row>
            )}
            {c.has_genesis && (
              <Row icon={<IconClock />} title="Schedule" desc={scheduleLine(c)} src="Genesis" on={Boolean(c.today)}>
                {c.today ? "Today" : c.genesis_seen_at ? "" : "Not yet"}
              </Row>
            )}
            <Row
              icon={<IconDevice />}
              title="Gradez"
              desc={
                c.student_login_email
                  ? `${c.first_name} signs in as ${c.student_login_email}`
                  : c.student_invite_email
                    ? `Invite sent to ${c.student_invite_email}`
                    : `${c.first_name}'s own homework app: just what's due next, one tap to tick it off`
              }
              on={Boolean(c.student_login_email)}
            >
              {panelBtn("student", login ? "Manage" : `Give ${c.first_name} a login`)}
            </Row>
          </ul>
        </div>
      )}

      <div className="fam-group">
        <div className="eyebrow">Family</div>
        <ul className="fam-rows">
          <Row icon={<IconUsers />} title="Guardians" desc={guardiansLine(c)} on={c.guardian_count > 1}>
            {panelBtn("guardian", "Invite")}
          </Row>
          {c.school_type === "elementary" && (
            <Row
              icon={<IconPalette />}
              title="Specials"
              desc={c.specials_count ? `${c.specials_count} day${c.specials_count === 1 ? "" : "s"} filled in, shown on your Today page` : "Art, PE or Music on the right day, on your Today page"}
              on={c.specials_count > 0}
            >
              {panelBtn("specials", c.specials_count ? "Edit" : "Add")}
            </Row>
          )}
          {c.school_type === "high" && (
            <Row icon={<IconGradCap />} title="Graduating class" desc={`Class events for ${c.first_name}'s year on the school page`} on={c.grad_year !== null}>
              <select
                value={c.grad_year ?? ""}
                onChange={(e) => onGradYear(e.target.value ? Number(e.target.value) : null)}
                aria-label={`${c.first_name}'s graduating class`}
              >
                <option value="">Not set</option>
                {gradYearOptions().map((y) => (
                  <option key={y} value={y}>
                    Class of {y}
                  </option>
                ))}
              </select>
            </Row>
          )}
        </ul>
      </div>

      {open && (
        <div className="fam-panel">
          {open === "specials" && <SpecialsEditor student={c} onClose={onClosePanel} />}
          {open === "guardian" && <GuardianInvite student={c} onClose={onClosePanel} />}
          {open === "student" && <StudentLoginInvite studentId={c.id} firstName={c.first_name} />}
        </div>
      )}

      {!offers && <p className="fam-none">Homework and grades aren't available{c.school_name ? ` at ${c.school_name}` : ""} yet.</p>}
      <div className="fam-foot">
        <span>Student ID {c.student_id}</span>
        <button type="button" onClick={onRemove}>
          Remove from my family
        </button>
      </div>
    </div>
  );
}
