import { useCallback, useEffect, useState, type ReactNode } from "react";
import { apiFetch, apiGet, hasSession } from "./api";
import { localTodayIso } from "./courses";
import { CourseSheet } from "./components/CourseSheet";
import { DetailsTab } from "./components/DetailsTab";
import { FocusTab } from "./components/FocusTab";
import { SubjectsTab } from "./components/SubjectsTab";
import { TaskModal } from "./components/TaskModal";
import type {
  CourseProgress,
  CurrentUser,
  HelpDraft,
  HelpKind,
  LatePolicy,
  ScheduleResponse,
  Student,
  SuggestionState,
  TodoItem,
  TodoResponse,
} from "./types";

type Tab = "focus" | "subjects" | "calendar" | "details";

export function App() {
  const [students, setStudents] = useState<Student[]>([]);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [todo, setTodo] = useState<TodoResponse | null>(null);
  const [courses, setCourses] = useState<CourseProgress[]>([]);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [tab, setTab] = useState<Tab>("focus");
  const [open, setOpen] = useState<TodoItem | null>(null);
  const [openCourse, setOpenCourse] = useState<CourseProgress | null>(null);
  const [suggestions, setSuggestions] = useState<Record<string, SuggestionState>>({});
  const [helpKinds, setHelpKinds] = useState<HelpKind[]>([]);
  const [latePolicies, setLatePolicies] = useState<LatePolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const todayIso = localTodayIso();

  // Which student this app is for. A student's own login has exactly one -
  // itself - and skips the picker, the same rule KidsPage.tsx follows.
  useEffect(() => {
    if (!hasSession()) {
      setLoading(false);
      return;
    }
    (async () => {
      const me = await apiGet<CurrentUser>("/auth/me");
      if (me?.student_profile_id) {
        setStudentId(me.student_profile_id);
        return;
      }
      const list = await apiGet<Student[]>("/students");
      if (list && list.length > 0) {
        setStudents(list);
        // A guardian with several children has no "default" child, and
        // picking list[0] silently lands on whoever happens to sort first -
        // which during this prototype's first run was a test record with no
        // imported data, rendering a convincingly empty dashboard.
        const wanted = new URLSearchParams(window.location.search).get("student");
        const match = wanted && list.find((s) => s.id === wanted || s.student_id === wanted);
        setStudentId(match ? match.id : list[0].id);
      } else {
        setError("No students on this account yet.");
        setLoading(false);
      }
    })();
  }, []);

  const load = useCallback(async (id: string) => {
    const [todoRes, coursesRes, scheduleRes, kindsRes, policiesRes] = await Promise.all([
      apiGet<TodoResponse>(`/students/${id}/bucket3/todo`),
      apiGet<CourseProgress[]>(`/students/${id}/bucket3/progress`),
      apiGet<ScheduleResponse>(`/students/${id}/bucket3/schedule`),
      apiGet<HelpKind[]>(`/students/${id}/bucket3/help-kinds`),
      apiGet<LatePolicy[]>(`/students/${id}/bucket3/late-policies`),
    ]);
    if (!todoRes) setError("Couldn't load assignments.");
    setTodo(todoRes);
    setCourses(coursesRes ?? []);
    setSchedule(scheduleRes);
    setHelpKinds(kindsRes ?? []);
    setLatePolicies(policiesRes ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (studentId) void load(studentId);
  }, [studentId, load]);

  const toggleDone = async (item: TodoItem, done: boolean) => {
    if (!studentId) return;
    // Optimistic: the checkbox is the whole interaction on this screen, so
    // it must feel instant. A failed write re-loads and the row snaps back.
    setTodo((prev) => (prev ? reflectDone(prev, item.id, done) : prev));
    setOpen((prev) => (prev && prev.id === item.id ? { ...prev, done } : prev));
    const res = await apiFetch(`/students/${studentId}/bucket3/workitems/${item.id}/complete`, {
      method: "POST",
      body: JSON.stringify({ done }),
    });
    if (!res.ok) setError("Couldn't save that. Reloading…");
    await load(studentId);
  };

  // Only ever runs when she presses the button - never on load, never for
  // every card. The backend caches per class, so the second student in the
  // section (or the same one tomorrow) gets it without a model call.
  const suggest = async (item: TodoItem) => {
    if (!studentId) return;
    setSuggestions((s) => ({ ...s, [item.id]: { loading: true, text: null, declined: false, error: null } }));
    const res = await apiFetch(`/students/${studentId}/bucket3/suggestions/assignment/${item.id}`, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    setSuggestions((s) => ({
      ...s,
      [item.id]: res.ok
        ? { loading: false, text: body.text ?? null, declined: Boolean(body.declined), error: null }
        : {
            loading: false,
            text: null,
            declined: false,
            error:
              res.status === 503
                ? "Suggestions aren't set up on this server yet."
                : (body.detail as string | undefined) ?? "Couldn't get a suggestion right now.",
          },
    }));
  };

  /** Drafts the "I'm stuck" email and records that the ask happened. The
   * send itself is a mailto: the student presses - schoolz never sends mail
   * for them. Reloads afterwards so the item stops looking untouched. */
  const askTeacher = async (item: TodoItem, kind: string): Promise<HelpDraft | null> => {
    if (!studentId) return null;
    const res = await apiFetch(`/students/${studentId}/bucket3/workitems/${item.id}/ask-teacher`, {
      method: "POST",
      body: JSON.stringify({ kind }),
    });
    if (!res.ok) return null;
    const draft = (await res.json()) as HelpDraft;
    void load(studentId);
    return draft;
  };

  /** Record (or clear) a teacher's "I'll still take it" for one assignment.
   * Passing null clears it. Reloads because this can bring an item back
   * from behind the marking-period filter entirely. */
  const setException = async (item: TodoItem, accepted_until: string | null, note?: string): Promise<boolean> => {
    if (!studentId) return false;
    const path = `/students/${studentId}/bucket3/workitems/${item.id}/late-exception`;
    const res = accepted_until
      ? await apiFetch(path, { method: "PUT", body: JSON.stringify({ accepted_until, granted_note: note || null }) })
      : await apiFetch(path, { method: "DELETE" });
    if (res.ok) await load(studentId);
    return res.ok;
  };

  const savePolicy = async (policy: Partial<LatePolicy> & { course_key: string }): Promise<boolean> => {
    if (!studentId) return false;
    const res = await apiFetch(`/students/${studentId}/bucket3/late-policies`, {
      method: "PUT",
      body: JSON.stringify(policy),
    });
    if (res.ok) await load(studentId);
    return res.ok;
  };

  const deletePolicy = async (courseKey: string): Promise<void> => {
    if (!studentId) return;
    await apiFetch(`/students/${studentId}/bucket3/late-policies/${encodeURIComponent(courseKey)}`, {
      method: "DELETE",
    });
    await load(studentId);
  };

  const suggestionFor = (item: TodoItem): SuggestionState | null =>
    suggestions[item.id] ?? (item.suggestion ? { ...item.suggestion, loading: false, error: null } : null);

  if (!hasSession()) {
    return (
      <Shell tab={tab} setTab={setTab}>
        <div className="empty-state">
          <h2>Not signed in</h2>
          <p>
            This view shares its session with schoolz. <a href="/login">Sign in</a>, then come back.
          </p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell tab={tab} setTab={setTab} students={students} studentId={studentId} onPick={setStudentId}>
      {error && <div className="banner-error">{error}</div>}
      {loading ? (
        <div className="empty-state">
          <p>Loading…</p>
        </div>
      ) : tab === "focus" ? (
        <FocusTab todo={todo} todayIso={todayIso} onOpen={setOpen} onToggle={toggleDone} />
      ) : tab === "subjects" ? (
        <SubjectsTab courses={courses} schedule={schedule} onOpenCourse={setOpenCourse} />
      ) : tab === "details" ? (
        <DetailsTab
          todo={todo}
          courses={courses}
          todayIso={todayIso}
          policies={latePolicies}
          studentId={studentId}
          onSavePolicy={savePolicy}
          onDeletePolicy={deletePolicy}
          onOpen={setOpen}
          onToggle={toggleDone}
        />
      ) : (
        <div className="empty-state">
          <h2>Calendar</h2>
          <p>Not built in this prototype — the Focus and Subjects tabs are the ones under test.</p>
        </div>
      )}
      {openCourse && todo && (
        <CourseSheet
          course={openCourse}
          items={[...todo.missing, ...todo.due, ...todo.no_due_date, ...todo.done].filter(
            (i) => i.course_name === openCourse.course_name,
          )}
          todayIso={todayIso}
          onClose={() => setOpenCourse(null)}
          onOpenItem={setOpen}
          onToggle={toggleDone}
        />
      )}
      {open && (
        <TaskModal
          item={open}
          suggestion={suggestionFor(open)}
          helpKinds={helpKinds}
          onSuggest={suggest}
          onAskTeacher={askTeacher}
          onSetException={setException}
          onClose={() => setOpen(null)}
          onToggle={toggleDone}
        />
      )}
    </Shell>
  );
}

/** Applies a done/undone change to the local copy, moving the item between
 * buckets so the counts and lists stay consistent until the reload lands. */
function reflectDone(todo: TodoResponse, itemId: string, done: boolean): TodoResponse {
  const all = [...todo.missing, ...todo.due, ...todo.done, ...todo.no_due_date];
  const target = all.find((i) => i.id === itemId);
  if (!target) return todo;
  const updated = { ...target, done, done_source: done ? "marked" : null };
  const without = (list: TodoItem[]) => list.filter((i) => i.id !== itemId);
  const next: TodoResponse = {
    ...todo,
    missing: without(todo.missing),
    due: without(todo.due),
    done: without(todo.done),
    no_due_date: without(todo.no_due_date),
  };
  if (done) next.done = [updated, ...next.done];
  else if (!updated.due_date) next.no_due_date = [updated, ...next.no_due_date];
  else if (updated.due_date < todayIsoSafe()) next.missing = [updated, ...next.missing];
  else next.due = [updated, ...next.due];
  const doneCount = next.done.length;
  const total = next.missing.length + next.due.length + next.done.length;
  next.progress = {
    ...todo.progress,
    done: doneCount,
    missing: next.missing.length,
    due: next.due.length,
    total,
    percent: total ? Math.round((doneCount * 100) / total) : null,
  };
  return next;
}

function todayIsoSafe(): string {
  return localTodayIso();
}

function Shell({
  children,
  tab,
  setTab,
  students = [],
  studentId = null,
  onPick,
}: {
  children: ReactNode;
  tab: Tab;
  setTab: (t: Tab) => void;
  students?: Student[];
  studentId?: string | null;
  onPick?: (id: string) => void;
}) {
  const title =
    tab === "focus" ? "Focus Dashboard" : tab === "subjects" ? "Subjects & Clubs" : tab === "details" ? "Details" : "Calendar";
  const current = students.find((s) => s.id === studentId);
  return (
    <div className="app">
      <header className="app-header">
        <h1>{title}</h1>
        {students.length > 1 && onPick ? (
          <select className="who-select" value={studentId ?? ""} onChange={(e) => onPick(e.target.value)} aria-label="Child">
            {students.map((s) => (
              <option key={s.id} value={s.id}>
                {s.first_name}
              </option>
            ))}
          </select>
        ) : (
          current && <span className="who">{current.first_name}</span>
        )}
      </header>
      <main className="app-main">{children}</main>
      <nav className="tabbar" aria-label="Sections">
        {/* This app is a separate build served from /focus/ (see
            schoolz's nginx.conf.template) sharing only the session, not a
            route - a plain <a> forces the real browser navigation back
            into schoolz's own SPA rather than trying to client-route
            somewhere this app has no match for. */}
        <a className="tab" href="/">
          <IconHome />
          <span>Today</span>
        </a>
        <TabButton current={tab} value="focus" label="Focus" onSelect={setTab} icon={<IconCompass />} />
        <TabButton current={tab} value="subjects" label="Subjects" onSelect={setTab} icon={<IconGrid />} />
        <TabButton current={tab} value="calendar" label="Calendar" onSelect={setTab} icon={<IconCalendar />} />
        <TabButton current={tab} value="details" label="Details" onSelect={setTab} icon={<IconList />} />
      </nav>
    </div>
  );
}

function TabButton({
  current,
  value,
  label,
  onSelect,
  icon,
}: {
  current: Tab;
  value: Tab;
  label: string;
  onSelect: (t: Tab) => void;
  icon: React.ReactNode;
}) {
  const active = current === value;
  return (
    <button
      type="button"
      className={`tab${active ? " active" : ""}`}
      aria-current={active ? "page" : undefined}
      onClick={() => onSelect(value)}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function IconHome() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 11 12 3l9 8" />
      <path d="M5 10v10h14V10" />
    </svg>
  );
}

function IconList() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 6h12M8 12h12M8 18h12" />
      <path d="M4 6h.01M4 12h.01M4 18h.01" />
    </svg>
  );
}

function IconCompass() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="m15.5 8.5-2 5-5 2 2-5z" />
    </svg>
  );
}

function IconGrid() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="4" width="6.5" height="6.5" rx="1.5" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" />
    </svg>
  );
}

function IconCalendar() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3.5" y="5" width="17" height="15" rx="2" />
      <path d="M3.5 9.5h17M8 3.5v3M16 3.5v3" />
    </svg>
  );
}
