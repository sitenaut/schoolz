import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiFetch } from "../api";
import { StudentLoginInvite } from "../components/StudentLoginInvite";
import { IconCheck, IconChevronLeft, IconMail, IconRefresh, IconUpload } from "../components/icons";
import { todayKey } from "../lib/calendar";

// Kids view v2 (docs/KIDS_VIEW_V2_DESIGN.md). Parent and student see the same
// page and the same data; "Focused" shows only right now / one next thing /
// one progress bar, "Everything" shows the rest. Built for readers who may
// have ADHD: one accent color for "needs attention", no auto-refreshing
// content, one obvious action per card.

type ScheduleBlock = {
  source: "list" | "daily";
  period: string;
  schedule_date: string | null;
  course_name: string;
  teacher: string | null;
  room: string | null;
  term: string | null;
  days: string | null;
  time_start: string | null;
  time_end: string | null;
};

type Schedule = { cycle_date: string | null; cycle_label: string | null; daily: ScheduleBlock[]; list_view: ScheduleBlock[] };

type ImportResult = {
  captures_processed: number;
  captures_skipped_duplicate: number;
  schedule_blocks_upserted: number;
  work_items_upserted: number;
  grade_entries_upserted: number;
  page_kinds_seen: number;
  identity_mismatches: string[];
};

type Student = {
  id: string;
  first_name: string;
  last_name: string;
  student_id: string;
  school_name: string | null;
  viewer_role: "guardian" | "student";
};


type CourseGrade = {
  course_code: string;
  course_section: string;
  course_name: string | null;
  marking_period: string;
  grade_percent: number | null;
  last_grade_posted: string | null;
};

type GradeEntry = {
  external_uid: string;
  course_code: string;
  course_section: string;
  course_name: string | null;
  marking_period: string | null;
  weekday_date: string;
  title: string;
  description: string | null;
  category: string | null;
  score_earned: number | null;
  score_possible: number | null;
  percent: number | null;
  status: string | null;
  is_updated: boolean;
};

type MarkingPeriod = { label: string; start_date: string; end_date: string };

type Grades = {
  course_grades: CourseGrade[];
  entries: GradeEntry[];
  marking_periods: MarkingPeriod[];
  marking_period_discrepancies: string[];
};

type WorkItem = { external_uid: string; course_name: string | null; title: string; due_raw: string | null };

type AuditMatched = { title: string; classroom: WorkItem | null; genesis: GradeEntry | null };

type Audit = {
  matched: AuditMatched[];
  classroom_only: WorkItem[];
  classroom_only_all_time: WorkItem[];
  genesis_only: GradeEntry[];
  current_marking_period: string | null;
  counts: Record<string, number>;
};

type NowBlock = {
  period: string;
  period_number: string | null;
  course_name: string;
  teacher: string | null;
  teacher_emails: string[];
  room: string | null;
  time_start: string | null;
  time_end: string | null;
  minutes_in: number | null;
  minutes_left: number | null;
  is_current: boolean;
};

type RightNow = {
  schedule_date: string | null;
  stale: boolean;
  cycle_label: string | null;
  school_day_over: boolean;
  current: NowBlock | null;
  next: NowBlock | null;
  blocks: NowBlock[];
};

type TodoItem = {
  id: string;
  title: string;
  item_type: string;
  course_name: string | null;
  due_raw: string | null;
  due_date: string | null;
  category: "missing" | "due" | "done" | "no_due_date";
  done: boolean;
  done_source: "marked" | "classroom" | "genesis" | null;
  marked_by: string | null;
  classroom_status: string | null;
  grade: { score_earned: number | null; score_possible: number | null; percent: number | null; status: string | null } | null;
  teacher_name: string | null;
  teacher_emails: string[];
  link: string | null;
  suggestion: { text: string | null; declined: boolean } | null;
};

type Todo = {
  current_marking_period: MarkingPeriod | null;
  progress: { done: number; missing: number; due: number; total: number; percent: number | null };
  next_action: TodoItem | null;
  missing: TodoItem[];
  due: TodoItem[];
  done: TodoItem[];
  no_due_date: TodoItem[];
};

type Announcement = {
  id: string;
  title: string;
  course_name: string | null;
  teacher_name: string | null;
  teacher_emails: string[];
  posted_raw: string | null;
  posted_date: string | null;
  body: string | null;
  link: string | null;
};

type CourseProgress = {
  course_key: string;
  course_name: string;
  grade_percent: number | null;
  marking_period: string | null;
  total: number;
  done: number;
  missing: number;
  due_soon: number;
  completion_pct: number | null;
  low_grade_entries: { title: string; percent: number }[];
  teacher_name: string | null;
  teacher_emails: string[];
};

type SuggestionState = { loading: boolean; text: string | null; declined: boolean; error: string | null; open: boolean };

type ViewMode = "focused" | "full";
type Tab = "todo" | "schedule" | "classes" | "grades" | "announcements" | "audit";

const MODE_KEY = "schoolz_kids_view_mode";

function loadMode(role: Student["viewer_role"]): ViewMode {
  try {
    const saved = localStorage.getItem(MODE_KEY);
    if (saved === "focused" || saved === "full") return saved;
  } catch {
    /* storage unavailable - fall through to the default */
  }
  // A student lands in Focused by default ("just tell me what to do next");
  // a guardian lands on the fuller overview. Either can switch.
  return role === "student" ? "focused" : "full";
}

async function getJson<T>(path: string, fallback: T): Promise<T> {
  const res = await apiFetch(path);
  return res.ok ? ((await res.json()) as T) : fallback;
}

// Classroom hrefs in a capture are relative ("/u/2/c/.../a/.../details").
// Prefixing the bare origin lands on the right page; Classroom resolves the
// signed-in account itself.
function classroomLink(link: string | null): string | null {
  if (!link) return null;
  return link.startsWith("http") ? link : `https://classroom.google.com${link}`;
}

function mailtoHref(emails: string[], subject?: string): string | null {
  if (!emails.length) return null;
  return `mailto:${emails.join(",")}${subject ? `?subject=${encodeURIComponent(subject)}` : ""}`;
}

function addDays(key: string, n: number): string {
  const d = new Date(`${key}T12:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function RichLines({ text }: { text: string }) {
  return (
    <>
      {text
        .split("\n")
        .filter((line) => line.trim())
        .map((line, i) => (
          <div key={i}>
            {line.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
              part.startsWith("**") && part.endsWith("**") ? <strong key={j}>{part.slice(2, -2)}</strong> : <span key={j}>{part}</span>,
            )}
          </div>
        ))}
    </>
  );
}

export function KidsDetailPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const base = `/students/${studentId}/bucket3`;
  const [student, setStudent] = useState<Student | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [now, setNow] = useState<RightNow | null>(null);
  const [todo, setTodo] = useState<Todo | null>(null);
  const [courses, setCourses] = useState<CourseProgress[]>([]);
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [grades, setGrades] = useState<Grades | null>(null);
  const [audit, setAudit] = useState<Audit | null>(null);
  const [mode, setMode] = useState<ViewMode | null>(null);
  const [tab, setTab] = useState<Tab>("todo");
  const [suggestions, setSuggestions] = useState<Record<string, SuggestionState>>({});

  const loadTodo = useCallback(async () => {
    const [t, c, au] = await Promise.all([
      getJson<Todo | null>(`${base}/todo`, null),
      getJson<CourseProgress[]>(`${base}/progress`, []),
      getJson<Audit | null>(`${base}/audit`, null),
    ]);
    setTodo(t);
    setCourses(c);
    setAudit(au);
  }, [base]);

  const loadNow = useCallback(async () => setNow(await getJson<RightNow | null>(`${base}/right-now`, null)), [base]);

  const loadAll = useCallback(async () => {
    const res = await apiFetch(`${base}/student`);
    if (!res.ok) {
      setNotFound(true);
      return;
    }
    setStudent(await res.json());
    const [a, s, g] = await Promise.all([
      getJson<Announcement[]>(`${base}/announcements`, []),
      getJson<Schedule | null>(`${base}/schedule`, null),
      getJson<Grades | null>(`${base}/grades`, null),
      loadNow(),
      loadTodo(),
    ]);
    setAnnouncements(a);
    setSchedule(s);
    setGrades(g);
  }, [base, loadNow, loadTodo]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Refresh "right now" when the tab comes back into view, not on a timer -
  // content shifting while someone is reading it is exactly the distraction
  // this page is meant to avoid.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") loadNow();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [loadNow]);

  useEffect(() => {
    if (student && mode === null) setMode(loadMode(student.viewer_role));
  }, [student, mode]);

  const changeMode = (next: ViewMode) => {
    setMode(next);
    try {
      localStorage.setItem(MODE_KEY, next);
    } catch {
      /* not persisted - still switches for this visit */
    }
  };

  const toggleDone = async (item: TodoItem) => {
    await apiFetch(`${base}/workitems/${item.id}/complete`, { method: "POST", body: JSON.stringify({ done: !item.done }) });
    await loadTodo();
  };

  const suggest = async (item: TodoItem) => {
    const existing =
      suggestions[item.id] ??
      (item.suggestion ? { loading: false, text: item.suggestion.text, declined: item.suggestion.declined, error: null, open: false } : undefined);
    if (existing && (existing.text || existing.declined)) {
      setSuggestions((s) => ({ ...s, [item.id]: { ...existing, open: !existing.open } }));
      return;
    }
    setSuggestions((s) => ({ ...s, [item.id]: { loading: true, text: null, declined: false, error: null, open: true } }));
    const res = await apiFetch(`${base}/suggestions/assignment/${item.id}`, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    setSuggestions((s) => ({
      ...s,
      [item.id]: res.ok
        ? { loading: false, text: body.text ?? null, declined: Boolean(body.declined), error: null, open: true }
        : {
            loading: false,
            text: null,
            declined: false,
            error: res.status === 503 ? "Suggestions aren't set up on this server yet." : body.detail ?? "Couldn't get a suggestion right now.",
            open: true,
          },
    }));
  };

  if (notFound) {
    return (
      <div className="page">
        <div className="empty">
          This student isn't on your profile. <Link to="/kids">Back to Kids</Link>
        </div>
      </div>
    );
  }
  if (!student || !mode) return <p className="note" style={{ margin: "3rem" }}>Loading…</p>;

  const isGuardian = student.viewer_role === "guardian";
  const hasAnyData = Boolean((now && now.blocks.length) || (todo && todo.progress.total + todo.no_due_date.length + todo.done.length));

  return (
    <div className="page">
      {isGuardian && (
        <Link to="/kids" className="back-link">
          <IconChevronLeft /> Kids
        </Link>
      )}
      <div className="kids-hd">
        <div>
          <div className="eyebrow">{isGuardian ? student.school_name : "Your school day"}</div>
          <h1>
            {student.first_name} {student.last_name}
          </h1>
          <p className="note">{isGuardian ? `Student ID ${student.student_id}` : student.school_name}</p>
        </div>
        <div className="tabs" role="group" aria-label="How much to show">
          <button className={`tab ${mode === "focused" ? "active" : ""}`} onClick={() => changeMode("focused")}>
            Focused
          </button>
          <button className={`tab ${mode === "full" ? "active" : ""}`} onClick={() => changeMode("full")}>
            Everything
          </button>
        </div>
      </div>

      <RightNowCard now={now} />

      {mode === "focused" ? (
        <FocusedView
          todo={todo}
          suggestions={suggestions}
          onToggle={toggleDone}
          onSuggest={suggest}
          onShowAll={() => changeMode("full")}
        />
      ) : (
        <>
          <ProgressCard todo={todo} />
          <div className="tabs kids-tabs">
            {(
              [
                ["todo", "To-do"],
                ["schedule", "Schedule"],
                ["classes", "Classes"],
                ["grades", "Grades"],
                ["announcements", `Announcements${announcements.length ? ` (${announcements.length})` : ""}`],
                ["audit", "Classroom vs. Genesis"],
              ] as [Tab, string][]
            ).map(([key, label]) => (
              <button key={key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </div>
          {tab === "todo" && <TodoTab todo={todo} base={base} suggestions={suggestions} onToggle={toggleDone} onSuggest={suggest} />}
          {tab === "schedule" && <ScheduleTab schedule={schedule} />}
          {tab === "classes" && <ClassesTab courses={courses} />}
          {tab === "grades" && <GradesTab grades={grades} />}
          {tab === "announcements" && <AnnouncementsTab items={announcements} />}
          {tab === "audit" && <AuditTab audit={audit} />}
          <ManageSection student={student} base={base} openByDefault={!hasAnyData} onChanged={loadAll} />
        </>
      )}
    </div>
  );
}

function RightNowCard({ now }: { now: RightNow | null }) {
  if (!now || now.blocks.length === 0) {
    return (
      <div className="card kids-now">
        <div className="eyebrow">Right now</div>
        <p className="note" style={{ margin: "4px 0 0" }}>
          No schedule captured yet — capture the Genesis student summary page to see today's classes here.
        </p>
      </div>
    );
  }
  if (now.stale) {
    return (
      <div className="card kids-now">
        <div className="eyebrow">Right now</div>
        <p className="note" style={{ margin: "4px 0 0" }}>
          The last schedule captured was for {now.schedule_date}, not today — capture today's Genesis summary to see what's
          happening now.
        </p>
      </div>
    );
  }
  const cur = now.current;
  const next = now.next;
  const teacherMail = cur ? mailtoHref(cur.teacher_emails, `Question about ${cur.course_name}`) : null;
  return (
    <div className="card kids-now">
      {cur ? (
        <>
          <div className="eyebrow">
            {["Right now", cur.period_number && `Period ${cur.period_number}`, `Block ${cur.period}`, now.cycle_label && `Cycle ${now.cycle_label}`]
              .filter(Boolean)
              .join(" · ")}
          </div>
          <div className="course">{cur.course_name}</div>
          <div className="sub">{[cur.room && `Room ${cur.room}`, cur.teacher, `${cur.time_start}–${cur.time_end}`].filter(Boolean).join(" · ")}</div>
          {cur.minutes_in != null && cur.minutes_left != null && (
            <>
              <div className="kids-bar" style={{ marginTop: 10 }}>
                <span style={{ width: `${Math.round((cur.minutes_in * 100) / Math.max(1, cur.minutes_in + cur.minutes_left))}%` }} />
              </div>
              <div className="sub" style={{ marginTop: 4 }}>
                {cur.minutes_left} min left
              </div>
            </>
          )}
          {teacherMail && (
            <div className="kids-links">
              <a href={teacherMail}>
                <IconMail /> Email teacher
              </a>
            </div>
          )}
          {next && (
            <p className="note" style={{ margin: "10px 0 0" }}>
              Up next: <strong>{next.course_name}</strong> at {next.time_start}
              {next.room ? ` · Room ${next.room}` : ""}
            </p>
          )}
        </>
      ) : now.school_day_over ? (
        <>
          <div className="eyebrow">Today{now.cycle_label ? ` · Cycle ${now.cycle_label}` : ""}</div>
          <div className="course">School's out for today</div>
        </>
      ) : next ? (
        <>
          <div className="eyebrow">
            {["Up next", next.period_number && `Period ${next.period_number}`, `Block ${next.period}`].filter(Boolean).join(" · ")}
          </div>
          <div className="course">{next.course_name}</div>
          <div className="sub">{[`Starts ${next.time_start}`, next.room && `Room ${next.room}`, next.teacher].filter(Boolean).join(" · ")}</div>
        </>
      ) : null}
      <details style={{ marginTop: 10 }}>
        <summary className="note" style={{ cursor: "pointer", margin: 0 }}>
          Today's full schedule
        </summary>
        <ul className="item-list" style={{ marginTop: 8 }}>
          {now.blocks.map((b) => (
            <li key={`${b.period}-${b.time_start}`} className="item-card" style={b.is_current ? { borderColor: "var(--primary)" } : undefined}>
              <span className="item-title">
                {b.period_number ? `Period ${b.period_number}` : b.period} · {b.course_name}
              </span>
              <div className="item-desc">
                {[`${b.time_start}–${b.time_end}`, `Block ${b.period}`, b.room && `Room ${b.room}`, b.teacher].filter(Boolean).join(" · ")}
              </div>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function ProgressCard({ todo }: { todo: Todo | null }) {
  if (!todo || todo.progress.total === 0) return null;
  const p = todo.progress;
  const pct = p.percent ?? 0;
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <div className="section-title" style={{ margin: 0 }}>
          {todo.current_marking_period ? `${todo.current_marking_period.label} progress` : "Progress"}
        </div>
        <strong>
          {p.done} of {p.total} done
        </strong>
      </div>
      <div className={`kids-bar ${pct === 100 ? "ok" : ""}`} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} style={{ marginTop: 8 }}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="kids-counts">
        {p.missing > 0 && <span className="tag deadline">{p.missing} missing</span>}
        <span className="tag">{p.due} coming up</span>
        <span className="tag done">{p.done} done</span>
      </div>
    </div>
  );
}

function SuggestionBox({ state }: { state: SuggestionState | undefined }) {
  if (!state || !state.open) return null;
  if (state.loading) return <div className="kids-suggest">Thinking…</div>;
  if (state.error) return <div className="banner bad" style={{ marginTop: 8 }}>{state.error}</div>;
  if (state.declined)
    return (
      <div className="kids-suggest">
        The title doesn't say enough to suggest a specific approach — open it in Classroom, or ask the teacher what they're looking for.
      </div>
    );
  return state.text ? (
    <div className="kids-suggest">
      <RichLines text={state.text} />
    </div>
  ) : null;
}

function doneLabel(item: TodoItem): string | null {
  if (!item.done) return null;
  if (item.done_source === "marked") return item.marked_by ? `marked done by ${item.marked_by}` : "marked done";
  if (item.done_source === "classroom") return `${(item.classroom_status ?? "done").toLowerCase()} in Classroom`;
  if (item.done_source === "genesis") return "graded in Genesis";
  return null;
}

function GradeTag({ grade }: { grade: TodoItem["grade"] }) {
  if (!grade) return null;
  if (grade.percent != null) return <span className={grade.percent < 50 ? "tag deadline" : "tag done"}>{grade.percent}%</span>;
  if (grade.status) return <span className={grade.status === "Missing" ? "tag deadline" : "tag"}>{grade.status}</span>;
  return null;
}

function TodoRow({
  item,
  suggestion,
  onToggle,
  onSuggest,
}: {
  item: TodoItem;
  suggestion: SuggestionState | undefined;
  onToggle: (item: TodoItem) => void;
  onSuggest: (item: TodoItem) => void;
}) {
  const link = classroomLink(item.link);
  const mail = mailtoHref(item.teacher_emails, `Question about: ${item.title}${item.course_name ? ` (${item.course_name})` : ""}`);
  const hasTips = Boolean(suggestion?.text || suggestion?.declined || item.suggestion);
  return (
    <li className={`item-card kids-row ${item.category}`}>
      <button
        className={`kids-check ${item.done ? "on" : ""}`}
        onClick={() => onToggle(item)}
        aria-pressed={item.done}
        aria-label={item.done ? `Mark "${item.title}" not done` : `Mark "${item.title}" done`}
      >
        {item.done && <IconCheck />}
      </button>
      <div className="body">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
          <span className="item-title">
            {link ? (
              <a href={link} target="_blank" rel="noreferrer">
                {item.title}
              </a>
            ) : (
              item.title
            )}
          </span>
          <GradeTag grade={item.grade} />
        </div>
        <div className="item-desc">
          {[item.course_name, item.due_raw && (item.category === "missing" ? `was due ${item.due_raw}` : `due ${item.due_raw}`), doneLabel(item)]
            .filter(Boolean)
            .join(" · ")}
        </div>
        {!item.done && (
          <div className="kids-links">
            <button onClick={() => onSuggest(item)}>{suggestion?.open ? "Hide tips" : hasTips ? "Show tips" : "How do I start?"}</button>
            {mail && (
              <a href={mail}>
                <IconMail /> Email teacher
              </a>
            )}
          </div>
        )}
        <SuggestionBox state={suggestion} />
      </div>
    </li>
  );
}

function FocusedView({
  todo,
  suggestions,
  onToggle,
  onSuggest,
  onShowAll,
}: {
  todo: Todo | null;
  suggestions: Record<string, SuggestionState>;
  onToggle: (item: TodoItem) => void;
  onSuggest: (item: TodoItem) => void;
  onShowAll: () => void;
}) {
  if (!todo) return <div className="empty">Nothing imported yet.</div>;
  const next = todo.next_action;
  const mail = next ? mailtoHref(next.teacher_emails, `Question about: ${next.title}${next.course_name ? ` (${next.course_name})` : ""}`) : null;
  return (
    <>
      {next ? (
        <div className="card kids-next">
          <div className="eyebrow">{next.category === "missing" ? "Catch up on this first" : "Do this next"}</div>
          <div className="title">{next.title}</div>
          <p className="note" style={{ marginBottom: 12 }}>
            {[next.course_name, next.due_raw && (next.category === "missing" ? `was due ${next.due_raw}` : `due ${next.due_raw}`)].filter(Boolean).join(" · ")}
          </p>
          <div className="actions bare" style={{ flexWrap: "wrap" }}>
            <button className="action primary" onClick={() => onToggle(next)}>
              <IconCheck /> Mark done
            </button>
            <button className="action" onClick={() => onSuggest(next)}>
              {suggestions[next.id]?.open ? "Hide tips" : "How do I start?"}
            </button>
            {mail && (
              <a className="action" href={mail}>
                <IconMail /> Email teacher
              </a>
            )}
          </div>
          <SuggestionBox state={suggestions[next.id]} />
        </div>
      ) : (
        <div className="card kids-next">
          <div className="eyebrow">All caught up</div>
          <div className="title">Nothing due or missing right now</div>
        </div>
      )}
      <ProgressCard todo={todo} />
      <button className="action" onClick={onShowAll}>
        Show everything
      </button>
    </>
  );
}

function groupDue(items: TodoItem[], today: string): { label: string; items: TodoItem[] }[] {
  const tomorrow = addDays(today, 1);
  const dayOfWeek = new Date(`${today}T12:00:00`).getDay(); // 0 = Sunday
  const endOfWeek = addDays(today, dayOfWeek === 0 ? 0 : 7 - dayOfWeek);
  const groups: { label: string; items: TodoItem[] }[] = [
    { label: "Due today", items: [] },
    { label: "Due tomorrow", items: [] },
    { label: "Later this week", items: [] },
    { label: "Coming up", items: [] },
  ];
  for (const item of items) {
    const d = item.due_date ?? "";
    if (d <= today) groups[0].items.push(item);
    else if (d === tomorrow) groups[1].items.push(item);
    else if (d <= endOfWeek) groups[2].items.push(item);
    else groups[3].items.push(item);
  }
  return groups;
}

function TodoTab({
  todo,
  base,
  suggestions,
  onToggle,
  onSuggest,
}: {
  todo: Todo | null;
  base: string;
  suggestions: Record<string, SuggestionState>;
  onToggle: (item: TodoItem) => void;
  onSuggest: (item: TodoItem) => void;
}) {
  const [plan, setPlan] = useState<{ loading: boolean; text: string | null; error: string | null }>({ loading: false, text: null, error: null });
  if (!todo) return <div className="empty">Nothing imported yet — use "Update data" below.</div>;

  const makePlan = async () => {
    setPlan({ loading: true, text: null, error: null });
    const res = await apiFetch(`${base}/suggestions/plan`, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    setPlan(
      res.ok
        ? { loading: false, text: body.text ?? null, error: null }
        : { loading: false, text: null, error: res.status === 503 ? "Suggestions aren't set up on this server yet." : body.detail ?? "Couldn't make a plan right now." },
    );
  };

  const row = (item: TodoItem) => (
    <TodoRow key={item.id} item={item} suggestion={suggestions[item.id]} onToggle={onToggle} onSuggest={onSuggest} />
  );
  const open = todo.missing.length + todo.due.length;

  return (
    <div>
      {open > 0 && (
        <div style={{ marginBottom: 8 }}>
          <button className="action" onClick={makePlan} disabled={plan.loading}>
            {plan.loading ? "Thinking…" : plan.text ? "Make a new plan" : "Suggest a plan"}
          </button>
          {plan.text && (
            <div className="kids-suggest">
              <RichLines text={plan.text} />
            </div>
          )}
          {plan.error && <div className="banner bad" style={{ marginTop: 8 }}>{plan.error}</div>}
        </div>
      )}

      {todo.missing.length > 0 && (
        <>
          <div className="kids-group missing">
            Missing · {todo.missing.length}
            {todo.current_marking_period && <span style={{ fontWeight: 400, color: "var(--ink-3)" }}> (this marking period)</span>}
          </div>
          <ul className="item-list">{todo.missing.map(row)}</ul>
        </>
      )}

      {groupDue(todo.due, todayKey()).map(
        (group) =>
          group.items.length > 0 && (
            <div key={group.label}>
              <div className="kids-group">
                {group.label} · {group.items.length}
              </div>
              <ul className="item-list">{group.items.map(row)}</ul>
            </div>
          ),
      )}

      {open === 0 && <div className="empty">Nothing due or missing right now.</div>}

      {todo.no_due_date.length > 0 && (
        <details className="accordion" style={{ marginTop: 16 }}>
          <summary>No due date · {todo.no_due_date.length}</summary>
          <div className="accordion-body">
            <ul className="item-list">{todo.no_due_date.map(row)}</ul>
          </div>
        </details>
      )}
      {todo.done.length > 0 && (
        <details className="accordion" style={{ marginTop: todo.no_due_date.length ? 0 : 16 }}>
          <summary>Done · {todo.done.length}</summary>
          <div className="accordion-body">
            <ul className="item-list">{todo.done.map(row)}</ul>
          </div>
        </details>
      )}
    </div>
  );
}

function ClassesTab({ courses }: { courses: CourseProgress[] }) {
  if (!courses.length) return <div className="empty">No classes yet — import Classroom and Genesis captures under "Update data".</div>;
  return (
    <ul className="item-list">
      {courses.map((c) => {
        const mail = mailtoHref(c.teacher_emails, `Question about ${c.course_name}`);
        return (
          <li key={c.course_key} className="item-card">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
              <span className="item-title">{c.course_name}</span>
              {c.grade_percent != null && <span className={c.grade_percent < 50 ? "tag deadline" : "tag done"}>{c.grade_percent}%</span>}
            </div>
            {c.total > 0 && (
              <>
                <div className={`kids-bar ${c.completion_pct === 100 ? "ok" : ""}`} style={{ marginTop: 8 }}>
                  <span style={{ width: `${c.completion_pct ?? 0}%` }} />
                </div>
                <div className="kids-counts">
                  <span className="tag">
                    {c.done} of {c.total} done
                  </span>
                  {c.missing > 0 && <span className="tag deadline">{c.missing} missing</span>}
                  {c.due_soon > 0 && <span className="tag">{c.due_soon} due this week</span>}
                </div>
              </>
            )}
            {c.low_grade_entries.length > 0 && (
              <div className="banner" style={{ marginTop: 10, marginBottom: 0 }}>
                <span>
                  Below 50%: {c.low_grade_entries.map((e) => `${e.title} (${e.percent}%)`).join(", ")} — ask the teacher whether makeup work is
                  possible.
                </span>
              </div>
            )}
            {mail && (
              <div className="kids-links">
                <a href={mail}>
                  <IconMail /> Email {c.teacher_name ?? "teacher"}
                </a>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function AnnouncementsTab({ items }: { items: Announcement[] }) {
  if (!items.length) return <div className="empty">No announcements captured yet — capture a class's Stream page in Classroom.</div>;
  return (
    <ul className="item-list">
      {items.map((a) => {
        const mail = mailtoHref(a.teacher_emails, `About your announcement: ${a.title}`);
        return (
          <li key={a.id} className="item-card">
            <div className="eyebrow">{[a.course_name, a.teacher_name, a.posted_raw].filter(Boolean).join(" · ")}</div>
            {a.body ? <div className="kids-body">{a.body}</div> : <div className="item-title">{a.title}</div>}
            {mail && (
              <div className="kids-links">
                <a href={mail}>
                  <IconMail /> Email {a.teacher_name ?? "teacher"}
                </a>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function ScheduleTab({ schedule }: { schedule: Schedule | null }) {
  if (!schedule || (schedule.daily.length === 0 && schedule.list_view.length === 0)) {
    return <div className="empty">No schedule imported yet — capture a Genesis student summary page.</div>;
  }
  return (
    <div>
      {schedule.daily.length > 0 && (
        <div className="card">
          <div className="section-title" style={{ margin: 0 }}>
            Schedule for {schedule.cycle_date}
            {schedule.cycle_label && ` — Cycle ${schedule.cycle_label}`}
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="kids-table">
              <thead>
                <tr>
                  <th>Block</th>
                  <th>Time</th>
                  <th>Class</th>
                  <th>Teacher</th>
                  <th>Room</th>
                </tr>
              </thead>
              <tbody>
                {schedule.daily.map((b) => (
                  <tr key={`${b.period}-${b.schedule_date}`}>
                    <td>{b.period}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {b.time_start} – {b.time_end}
                    </td>
                    <td>{b.course_name}</td>
                    <td>{b.teacher ?? "—"}</td>
                    <td>{b.room ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {schedule.list_view.length > 0 && (
        <details className="accordion">
          <summary>Full-year schedule</summary>
          <div className="accordion-body" style={{ overflowX: "auto" }}>
            <table className="kids-table">
              <thead>
                <tr>
                  <th>Block</th>
                  <th>Class</th>
                  <th>Term</th>
                  <th>Teacher</th>
                  <th>Room</th>
                  <th>Days</th>
                </tr>
              </thead>
              <tbody>
                {schedule.list_view.map((b) => (
                  <tr key={`${b.period}-${b.term}`}>
                    <td>{b.period}</td>
                    <td>{b.course_name}</td>
                    <td>{b.term ?? "—"}</td>
                    <td>{b.teacher ?? "—"}</td>
                    <td>{b.room ?? "—"}</td>
                    <td>{b.days ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function scoreLabel(e: GradeEntry): string {
  if (e.status) return e.status;
  if (e.score_earned != null && e.score_possible != null) return `${e.score_earned}/${e.score_possible} (${e.percent ?? "?"}%)`;
  if (e.score_possible != null) return `— / ${e.score_possible}`;
  return "—";
}

function scoreTagClass(e: GradeEntry): string {
  if (e.status === "Missing") return "tag deadline";
  if (e.percent != null && e.percent < 50) return "tag deadline";
  if (e.percent != null) return "tag done";
  return "tag";
}

function GradesTab({ grades }: { grades: Grades | null }) {
  if (!grades || grades.course_grades.length === 0) {
    return <div className="empty">No grades imported yet — capture a Genesis "Course Summary" gradebook page for each class.</div>;
  }
  return (
    <div>
      {grades.marking_periods.length > 0 && (
        <p className="note">Marking periods: {grades.marking_periods.map((mp) => `${mp.label} (${mp.start_date} – ${mp.end_date})`).join(" · ")}</p>
      )}
      {grades.marking_period_discrepancies.length > 0 && (
        <div className="banner bad">
          <span>
            {grades.marking_period_discrepancies.map((d) => (
              <div key={d}>{d}</div>
            ))}
          </span>
        </div>
      )}
      <div className="card">
        <div className="section-title" style={{ margin: 0 }}>
          Current grade by course
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="kids-table">
            <thead>
              <tr>
                <th>Course</th>
                <th>MP</th>
                <th>Grade</th>
                <th>Last graded</th>
              </tr>
            </thead>
            <tbody>
              {grades.course_grades.map((g) => (
                <tr key={`${g.course_code}-${g.course_section}-${g.marking_period}`}>
                  <td>{g.course_name ?? `Course ${g.course_code}-${g.course_section}`}</td>
                  <td>{g.marking_period}</td>
                  <td>
                    {g.grade_percent != null ? <span className={g.grade_percent < 50 ? "tag deadline" : "tag done"}>{g.grade_percent}%</span> : "—"}
                  </td>
                  <td>{g.last_grade_posted ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="section-title">Graded assignments</div>
      <ul className="item-list">
        {grades.entries.map((e) => (
          <li key={e.external_uid} className="item-card">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
              <span className="item-title">
                {e.title}
                {e.is_updated && (
                  <span className="tag new" style={{ marginLeft: 6 }}>
                    Updated
                  </span>
                )}
              </span>
              <span className={scoreTagClass(e)}>{scoreLabel(e)}</span>
            </div>
            <p className="item-desc" style={{ marginBottom: 0 }}>
              {[e.course_name ?? `${e.course_code}-${e.course_section}`, e.category, e.weekday_date].filter(Boolean).join(" · ")}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AuditTab({ audit }: { audit: Audit | null }) {
  if (!audit) return <div className="empty">Nothing imported yet.</div>;
  return (
    <div>
      <p className="note">
        What Classroom and Genesis each report, matched by assignment title. Teachers don't always keep both in sync, so a gap here
        doesn't necessarily mean work is missing — it may just mean only one system was updated.
        {audit.current_marking_period && ` "Only in Classroom" is limited to ${audit.current_marking_period} (${audit.counts.classroom_only_all_time} all-time).`}
      </p>
      <div className="section-title">In both · {audit.counts.matched}</div>
      {audit.matched.length === 0 ? (
        <p className="note">None yet.</p>
      ) : (
        <ul className="item-list">
          {audit.matched.map((m, i) => (
            <li key={`${m.title}-${i}`} className="item-card">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                <span className="item-title">{m.title}</span>
                {m.genesis && <span className={scoreTagClass(m.genesis)}>{scoreLabel(m.genesis)}</span>}
              </div>
              {m.classroom?.due_raw && <p className="item-desc" style={{ marginBottom: 0 }}>Classroom: due {m.classroom.due_raw}</p>}
            </li>
          ))}
        </ul>
      )}
      <div className="section-title">Only in Classroom · {audit.counts.classroom_only}</div>
      {audit.classroom_only.length === 0 ? (
        <p className="note">None.</p>
      ) : (
        <ul className="item-list">
          {audit.classroom_only.map((it) => (
            <li key={it.external_uid} className="item-card">
              <span className="item-title">{it.title}</span>
              <p className="item-desc" style={{ marginBottom: 0 }}>
                {[it.course_name, it.due_raw && `due ${it.due_raw}`].filter(Boolean).join(" · ")}
              </p>
            </li>
          ))}
        </ul>
      )}
      <div className="section-title">Only in Genesis · {audit.counts.genesis_only}</div>
      {audit.genesis_only.length === 0 ? (
        <p className="note">None.</p>
      ) : (
        <ul className="item-list">
          {audit.genesis_only.map((e) => (
            <li key={e.external_uid} className="item-card">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                <span className="item-title">{e.title}</span>
                <span className={scoreTagClass(e)}>{scoreLabel(e)}</span>
              </div>
              <p className="item-desc" style={{ marginBottom: 0 }}>{e.course_name ?? `${e.course_code}-${e.course_section}`}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ManageSection({
  student,
  base,
  openByDefault,
  onChanged,
}: {
  student: Student;
  base: string;
  openByDefault: boolean;
  onChanged: () => Promise<void>;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<"import" | "reprocess" | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    setResult(null);
    setBusy("import");
    try {
      const parsed = JSON.parse(await file.text());
      const res = await apiFetch(`${base}/import`, { method: "POST", body: JSON.stringify(parsed) });
      const body = await res.json();
      if (!res.ok) {
        setError(body.detail ?? "Import failed");
        return;
      }
      setResult(body);
      await onChanged();
    } catch {
      setError("That doesn't look like a Backpack Capture export (expected JSON with a captures[] array).");
    } finally {
      setBusy(null);
    }
  };

  const reprocess = async () => {
    setError(null);
    setResult(null);
    setBusy("reprocess");
    try {
      const res = await apiFetch(`${base}/reprocess`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) {
        setError(body.detail ?? "Couldn't re-read imported pages");
        return;
      }
      setResult(body);
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  return (
    <details className="accordion" style={{ marginTop: 24 }} open={openByDefault}>
      <summary>Update data{student.viewer_role === "guardian" ? " & family settings" : ""}</summary>
      <div className="accordion-body">
        <div className="actions bare" style={{ flexWrap: "wrap" }}>
          <button className="action primary" onClick={() => fileInputRef.current?.click()} disabled={busy !== null}>
            <IconUpload /> {busy === "import" ? "Importing…" : "Import capture"}
          </button>
          <button className="action" onClick={reprocess} disabled={busy !== null}>
            <IconRefresh /> {busy === "reprocess" ? "Re-reading…" : "Re-read imported pages"}
          </button>
        </div>
        {/* style, not the hidden attribute: the global `input { display: block }`
            rule in styles.css overrides [hidden]. */}
        <input ref={fileInputRef} type="file" accept="application/json" onChange={handleImport} style={{ display: "none" }} />
        <p className="note" style={{ marginTop: 10 }}>
          Upload the file you saved with <strong>Export capture</strong> in the Backpack Capture extension. Only pages for student ID{" "}
          {student.student_id} are imported.
          "Re-read" re-runs the latest parsing over pages already imported — useful after an app update.
        </p>
        {error && <div className="banner bad">{error}</div>}
        {result && (
          <div className="banner">
            <span>
              Read {result.captures_processed} page(s) — {result.work_items_upserted} assignment update(s), {result.grade_entries_upserted} grade
              update(s), {result.schedule_blocks_upserted} schedule block(s).
              {result.identity_mismatches.map((m) => (
                <span key={m} style={{ display: "block" }}>
                  {m}
                </span>
              ))}
            </span>
          </div>
        )}
        {student.viewer_role === "guardian" && (
          <div className="card" style={{ marginTop: 12, marginBottom: 0 }}>
            <StudentLoginInvite studentId={student.id} firstName={student.first_name} />
          </div>
        )}
      </div>
    </details>
  );
}

