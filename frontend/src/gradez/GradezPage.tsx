import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { gradezHref } from "../lib/gradezPath";
import { ROUTER_BASENAME } from "../lib/i18n";
import { apiFetch, apiGet } from "./api";
import { ClassAppearance } from "./components/ClassAppearance";
import { ClassPage } from "./components/ClassPage";
import { DataSheet } from "./components/DataSheet";
import { GradesTab, classRows, markingPeriodLabels, type ClassRow } from "./components/GradesTab";
import { IconCheck, IconChevronDown, IconChevronLeft, IconCircleCheck, IconHome, TabIcon } from "./components/icons";
import { LatePolicyEditor } from "./components/LatePolicyEditor";
import { ScheduleTab } from "./components/ScheduleTab";
import { Sheet } from "./components/Sheet";
import { TaskModal } from "./components/TaskModal";
import { TeachersTab } from "./components/TeachersTab";
import { TodoTab } from "./components/TodoTab";
import { displayCourseName, localTodayIso } from "./courses";
import { genesisKey } from "./format";
import { useCoursePreferences, type CourseNameOverrides } from "./lib/coursePreferences";
import { freshness, type Freshness } from "./lib/freshness";
import type {
  Announcement,
  CourseProgress,
  GradezTab,
  Grades,
  HelpDraft,
  HelpKind,
  LatePolicy,
  RightNow,
  ScheduleResponse,
  Student,
  SuggestionState,
  SyncStatus,
  TodoItem,
  TodoResponse,
  TodoView,
} from "./types";
import "./gradez.css";

const TABS: { tab: GradezTab; label: string }[] = [
  { tab: "todo", label: "To do" },
  { tab: "grades", label: "Grades" },
  { tab: "schedule", label: "Schedule" },
  { tab: "teachers", label: "Teachers" },
];

// Leaving Gradez is a page load, never a router navigation: this document
// started without analytics (lib/gradezPath.ts), and the rest of schoolz
// has to start with it.
const HOME_HREF = `${ROUTER_BASENAME}/`;
const FAMILY_HREF = `${ROUTER_BASENAME}/family`;

function tabOf(value: string | null): GradezTab {
  return value === "grades" || value === "schedule" || value === "teachers" ? value : "todo";
}

/** What each tab is for, in a line under its name. */
function purpose(tab: GradezTab, view: TodoView, firstName: string, isStudent: boolean): string {
  if (tab === "grades") return "How each class is going, and where to step in. Tap a class to see what is behind the grade.";
  if (tab === "schedule") {
    return `Where ${isStudent ? "you are" : `${firstName} is`} right now, and which classes meet on any school day.`;
  }
  if (tab === "teachers") return "What teachers posted and how to reach them. Look here for test dates and reminders.";
  return view === "next"
    ? "What to work on now. Only today, the next school day, and late work that still counts."
    : "Everything coming up, with late work that still counts.";
}

/** One class's row, in the marking period being looked at if it is there
 * and otherwise in whichever one lists it. */
function findClass(
  key: string,
  period: string | null,
  currentPeriod: string | null,
  periods: string[],
  courses: CourseProgress[],
  grades: Grades | null,
  names: CourseNameOverrides,
): { row: ClassRow; period: string | null } | null {
  for (const p of [period, currentPeriod, ...periods]) {
    const row = classRows(p, currentPeriod, courses, grades, names).find((r) => r.course_key === key);
    if (row) return { row, period: p };
  }
  return null;
}

/** A child's schoolwork on one page: To do, Grades, Schedule and Teachers.
 * A guardian and the child's own login see the same thing, less the
 * controls only a parent uses. Rendered outside the app shell, in a
 * document that loads no analytics (App.tsx's GradezDocument). */
export function GradezPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const profileId = user?.student_profile_id ?? null;

  // null while loading. A failed load is its own state: "no children" is
  // something only an answer can say.
  const [students, setStudents] = useState<Student[] | null>(null);
  const [studentsFailed, setStudentsFailed] = useState(false);
  const [studentsAsked, setStudentsAsked] = useState(0);

  const [todo, setTodo] = useState<TodoResponse | null>(null);
  // Null when the load failed, which is not "no classes".
  const [courses, setCourses] = useState<CourseProgress[] | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [scheduleFailed, setScheduleFailed] = useState(false);
  const [helpKinds, setHelpKinds] = useState<HelpKind[]>([]);
  const [latePolicies, setLatePolicies] = useState<LatePolicy[]>([]);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [grades, setGrades] = useState<Grades | null>(null);
  const [announcements, setAnnouncements] = useState<Announcement[] | null>(null);
  const [rightNow, setRightNow] = useState<RightNow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The clock as of the last load or return to the page, never a timer.
  const [now, setNow] = useState(() => Date.now());

  // The item whose sheet is open, as it was when tapped. What the sheet
  // shows is read from the current to-do by its id (below), so saving an
  // exception or asking the teacher shows up without closing it first.
  const [opened, setOpen] = useState<TodoItem | null>(null);
  const [suggestions, setSuggestions] = useState<Record<string, SuggestionState>>({});
  const [appearanceFor, setAppearanceFor] = useState<string | null>(null);
  const [policyFor, setPolicyFor] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [dataOpen, setDataOpen] = useState(() => params.get("sheet") === "data");
  const [pickedPeriod, setPickedPeriod] = useState<string | null>(null);
  const [pickedView, setPickedView] = useState<TodoView | null>(null);
  const { colors: courseColors, names: courseNames, setColor: setCourseColor, setName: setCourseName } = useCoursePreferences();

  const todayIso = localTodayIso();

  useEffect(() => {
    document.title = "Gradez";
  }, []);

  // Whose page this can be. A child's own login has exactly one: itself.
  useEffect(() => {
    let live = true;
    const ask = profileId
      ? apiGet<Student>(`/students/${profileId}/bucket3/student`).then((own) => (own ? [own] : null))
      : apiGet<Student[]>("/students");
    void ask.then((list) => {
      if (!live) return;
      if (list) setStudents(list);
      setStudentsFailed(!list);
    });
    return () => {
      live = false;
    };
  }, [profileId, studentsAsked]);

  // ?student= takes the schoolz id or the district's own, which is the one a
  // person knows. A guardian with several children has no default child, so
  // a link that names one always wins over whoever sorts first.
  const wanted = params.get("student");
  const student = students?.find((s) => s.id === wanted || s.student_id === wanted) ?? students?.[0] ?? null;
  const studentId = student?.id ?? null;
  const isStudent = student?.viewer_role === "student" || (profileId != null && profileId === studentId);

  // The child whose data is meant to be on screen. Switching child while a
  // load was in flight let the slower, previous child's answers land under
  // the new child's name (and a tick on them POSTed against the wrong one).
  const currentId = useRef<string | null>(null);

  // Nothing of the previous child's stays up while the next one loads. Reset
  // while rendering, not in an effect, so no frame shows the old child's work.
  const [shownId, setShownId] = useState<string | null>(null);
  if (shownId !== studentId) {
    setShownId(studentId);
    setLoading(true);
    setTodo(null);
    setCourses(null);
    setSchedule(null);
    setScheduleFailed(false);
    setSync(null);
    setGrades(null);
    setAnnouncements(null);
    setRightNow(null);
    setLatePolicies([]);
    setPickedPeriod(null);
    setOpen(null);
    setError(null);
  }

  // Each load sets state only once its answers are in (in .then), and only
  // if the same child is still the one on screen.
  const loadCore = useCallback(
    (id: string) =>
      Promise.all([
        apiGet<TodoResponse>(`/students/${id}/bucket3/todo`),
        apiGet<CourseProgress[]>(`/students/${id}/bucket3/progress`),
        apiGet<ScheduleResponse>(`/students/${id}/bucket3/schedule`),
        apiGet<HelpKind[]>(`/students/${id}/bucket3/help-kinds`),
        apiGet<LatePolicy[]>(`/students/${id}/bucket3/late-policies`),
        apiGet<SyncStatus>(`/students/${id}/bucket3/status`),
      ]).then(([todoRes, coursesRes, scheduleRes, kindsRes, policiesRes, syncRes]) => {
        if (currentId.current !== id) return;
        // A good load clears an earlier failure's banner, which otherwise stayed
        // up for the rest of the session.
        if (todoRes) setError(null);
        setTodo(todoRes);
        setCourses(coursesRes);
        setSchedule(scheduleRes);
        setScheduleFailed(!scheduleRes);
        setHelpKinds(kindsRes ?? []);
        setLatePolicies(policiesRes ?? []);
        setSync(syncRes);
        setNow(Date.now());
        setLoading(false);
      }),
    [],
  );

  const loadRightNow = useCallback(
    (id: string) =>
      apiGet<RightNow>(`/students/${id}/bucket3/right-now`).then((res) => {
        if (currentId.current !== id) return;
        setRightNow(res);
        setNow(Date.now());
      }),
    [],
  );

  // What only one tab needs. It loads alongside, and never holds up To do.
  const loadExtras = useCallback(
    (id: string) => {
      void loadRightNow(id);
      return Promise.all([apiGet<Grades>(`/students/${id}/bucket3/grades`), apiGet<Announcement[]>(`/students/${id}/bucket3/announcements`)]).then(
        ([gradesRes, postsRes]) => {
          if (currentId.current !== id) return;
          setGrades(gradesRes);
          setAnnouncements(postsRes);
        },
      );
    },
    [loadRightNow],
  );

  const reload = useCallback(
    async (id: string) => {
      void loadExtras(id);
      await loadCore(id);
    },
    [loadCore, loadExtras],
  );

  useEffect(() => {
    currentId.current = studentId;
    if (studentId) void reload(studentId);
  }, [studentId, reload]);

  // "Right now" is true for a few minutes. Coming back to the page asks
  // again; a timer would keep a phone in a pocket asking all day.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible" || !currentId.current) return;
      setNow(Date.now());
      void reload(currentId.current);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [reload]);

  const tab = tabOf(params.get("tab"));
  const classKey = params.get("class");
  const onClassPage = tab === "grades" && Boolean(classKey);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [tab, onClassPage, studentId]);

  const closeData = () => {
    setDataOpen(false);
    if (params.has("sheet")) {
      const next = new URLSearchParams(params);
      next.delete("sheet");
      setParams(next, { replace: true });
    }
  };

  const view: TodoView = pickedView ?? user?.todo_view ?? "next";
  // Kept on the account, so it is the same on the next device. A save that
  // fails still holds for this visit.
  const saveView = (next: TodoView) => {
    setPickedView(next);
    void apiFetch("/auth/me", { method: "PATCH", body: JSON.stringify({ todo_view: next }) }).catch(() => null);
  };

  const toggleDone = async (item: TodoItem, done: boolean) => {
    if (!studentId) return;
    // Optimistic: the checkbox is the whole interaction on this screen, so
    // it must feel instant. A failed write re-loads and the row snaps back,
    // a dropped connection included.
    setTodo((prev) => (prev ? reflectDone(prev, item.id, done) : prev));
    setOpen((prev) => (prev && prev.id === item.id ? { ...prev, done } : prev));
    try {
      const res = await apiFetch(`/students/${studentId}/bucket3/workitems/${item.id}/complete`, {
        method: "POST",
        body: JSON.stringify({ done }),
      });
      if (!res.ok) setError("Couldn't save that. Reloading…");
    } catch {
      setError("Couldn't save that. Reloading…");
    } finally {
      await loadCore(studentId);
    }
  };

  // Only ever runs when the button is pressed: never on load, never for
  // every card. The backend caches per class, so the second student in the
  // section (or the same one tomorrow) gets it without a model call.
  const suggest = async (item: TodoItem) => {
    if (!studentId) return;
    setSuggestions((s) => ({ ...s, [item.id]: { loading: true, text: null, declined: false, error: null } }));
    let res: Response;
    try {
      res = await apiFetch(`/students/${studentId}/bucket3/suggestions/assignment/${item.id}`, { method: "POST" });
    } catch {
      // Not left on "Thinking…" for good.
      setSuggestions((s) => ({
        ...s,
        [item.id]: { loading: false, text: null, declined: false, error: "Couldn't get a suggestion right now." },
      }));
      return;
    }
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
                : ((body.detail as string | undefined) ?? "Couldn't get a suggestion right now."),
          },
    }));
  };

  /** Drafts the "I'm stuck" email and records that the ask happened. The
   * send itself is a mailto: the student presses; schoolz never sends mail
   * for them. Reloads afterwards so the item stops looking untouched. */
  const askTeacher = async (item: TodoItem, kind: string): Promise<HelpDraft | null> => {
    if (!studentId) return null;
    const res = await apiFetch(`/students/${studentId}/bucket3/workitems/${item.id}/ask-teacher`, {
      method: "POST",
      body: JSON.stringify({ kind }),
    }).catch(() => null);
    if (!res?.ok) return null;
    const draft = (await res.json()) as HelpDraft;
    void loadCore(studentId);
    return draft;
  };

  /** Record (or clear) a teacher's "I'll still take it" for one assignment.
   * Passing null clears it. Reloads because this can bring an item back
   * from behind the marking-period filter entirely. */
  const setException = async (item: TodoItem, accepted_until: string | null, note?: string): Promise<boolean> => {
    if (!studentId) return false;
    const path = `/students/${studentId}/bucket3/workitems/${item.id}/late-exception`;
    const res = await (accepted_until
      ? apiFetch(path, { method: "PUT", body: JSON.stringify({ accepted_until, granted_note: note || null }) })
      : apiFetch(path, { method: "DELETE" })
    ).catch(() => null);
    if (res?.ok) await loadCore(studentId);
    return Boolean(res?.ok);
  };

  const savePolicy = async (policy: Partial<LatePolicy> & { course_key: string }): Promise<boolean> => {
    if (!studentId) return false;
    const res = await apiFetch(`/students/${studentId}/bucket3/late-policies`, {
      method: "PUT",
      body: JSON.stringify(policy),
    }).catch(() => null);
    if (res?.ok) await loadCore(studentId);
    return Boolean(res?.ok);
  };

  const deletePolicy = async (courseKey: string): Promise<void> => {
    if (!studentId) return;
    await apiFetch(`/students/${studentId}/bucket3/late-policies/${encodeURIComponent(courseKey)}`, {
      method: "DELETE",
    }).catch(() => null);
    await loadCore(studentId);
  };

  const fresh = freshness(sync, now);
  const allTodo = todo ? [...todo.missing, ...todo.due, ...todo.no_due_date, ...todo.done] : [];
  const open = opened ? (allTodo.find((i) => i.id === opened.id) ?? opened) : null;
  const suggestionFor = (item: TodoItem): SuggestionState | null =>
    suggestions[item.id] ?? (item.suggestion ? { ...item.suggestion, loading: false, error: null } : null);

  const currentPeriod = todo?.current_marking_period?.label ?? null;
  const periods = markingPeriodLabels(grades);
  const period = (pickedPeriod && periods.includes(pickedPeriod) ? pickedPeriod : null) ?? currentPeriod;

  const to = (next: GradezTab, extra?: Record<string, string>) => gradezHref(studentId, next, extra);
  const rawName = (key: string) =>
    courses?.find((c) => c.course_key === key)?.course_name ??
    grades?.course_grades.find((g) => genesisKey(g) === key)?.course_name ??
    key;

  // A class page opened from the list sits one step after it in history, so
  // going back to the list is Back, not a second copy of the list.
  const cameFromList = Boolean((location.state as { fromGrades?: boolean } | null)?.fromGrades);
  const backToList = (e: MouseEvent) => {
    if (!onClassPage || !cameFromList) return;
    e.preventDefault();
    navigate(-1);
  };

  const frame = (body: ReactNode, top?: ReactNode) => (
    <div className="gz-app">
      <div className="gz-top">
        {top ?? <Who students={students ?? []} student={student} onSwitch={() => setSwitching(true)} />}
        {studentId && <Updated fresh={fresh} onOpen={() => setDataOpen(true)} />}
      </div>
      {error && <div className="gz-banner-error">{error}</div>}
      {fresh && fresh.kind !== "never" && fresh.needsLogin && (
        <div className="gz-banner-warn">
          Backpack Capture can't read Google Classroom: sign in to Classroom again in Chrome on the computer it runs on.
        </div>
      )}
      <main className="gz-main">{body}</main>
      <nav className="gz-tabbar" aria-label="Gradez tabs">
        <a href={HOME_HREF}>
          <IconHome />
          <span>Today</span>
        </a>
        {TABS.map((t) => (
          <Link
            key={t.tab}
            to={to(t.tab)}
            replace
            aria-current={t.tab === tab ? "page" : undefined}
            onClick={t.tab === "grades" ? backToList : undefined}
          >
            <TabIcon tab={t.tab} />
            <span>{t.label}</span>
          </Link>
        ))}
      </nav>

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
          courseNames={courseNames}
        />
      )}
      {appearanceFor && (
        <ClassAppearance
          courseKey={appearanceFor}
          autoName={displayCourseName(rawName(appearanceFor))}
          customName={courseNames[appearanceFor]}
          customColor={courseColors[appearanceFor]}
          onSetName={(name) => setCourseName(appearanceFor, name)}
          onSetColor={(hex) => setCourseColor(appearanceFor, hex)}
          onClose={() => setAppearanceFor(null)}
        />
      )}
      {policyFor && studentId && (
        <Sheet onClose={() => setPolicyFor(null)} label="Late-work rule">
          <LatePolicyEditor
            courseKey={policyFor}
            courseName={displayCourseName(rawName(policyFor), courseNames[policyFor])}
            studentId={studentId}
            existing={latePolicies.find((p) => p.course_key === policyFor) ?? null}
            onSave={savePolicy}
            onDelete={deletePolicy}
            onClose={() => setPolicyFor(null)}
          />
        </Sheet>
      )}
      {switching && students && (
        <Sheet onClose={() => setSwitching(false)} label="Switch child">
          <h2 className="gz-sheet-heading">Whose page?</h2>
          <ul className="gz-card gz-list gz-children">
            {students.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="gz-child-row"
                  aria-current={s.id === studentId ? "true" : undefined}
                  onClick={() => {
                    setSwitching(false);
                    // A class belongs to one child, so the tab is kept and the class is not.
                    if (s.id !== studentId) navigate(gradezHref(s.id, tab), { replace: true });
                  }}
                >
                  <span className="gz-avatar" aria-hidden="true">
                    {s.first_name.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="gz-row-main">
                    <span className="gz-row-title">{s.first_name}</span>
                    {s.school_name && <span className="gz-row-sub">{s.school_name}</span>}
                  </span>
                  {s.id === studentId && <IconCheck />}
                </button>
              </li>
            ))}
          </ul>
        </Sheet>
      )}
      {dataOpen && student && (
        <DataSheet
          studentId={student.id}
          firstName={student.first_name}
          isStudent={isStudent}
          sync={sync}
          now={now}
          onClose={closeData}
          onChanged={() => void reload(student.id)}
        />
      )}
    </div>
  );

  if (!students) {
    return frame(
      studentsFailed ? (
        <LoadFailed
          what="this page"
          onRetry={() => {
            setStudentsFailed(false);
            setStudentsAsked((n) => n + 1);
          }}
        />
      ) : (
        <div className="gz-empty-state">
          <p>Loading…</p>
        </div>
      ),
    );
  }
  if (!student || !studentId) {
    return frame(
      <div className="gz-empty-state">
        <h2>No students on this account yet</h2>
        <p>Add your child on My family, and their schoolwork shows up here.</p>
        <a className="gz-btn" href={FAMILY_HREF}>
          My family
        </a>
      </div>,
    );
  }
  if (loading) {
    return frame(
      <div className="gz-empty-state">
        <p>Loading…</p>
      </div>,
    );
  }

  const retry = () => {
    setLoading(true);
    void reload(studentId);
  };
  const shared = { courseColors, courseNames };

  if (onClassPage && classKey) {
    const found = courses ? findClass(classKey, period, currentPeriod, periods, courses, grades, courseNames) : null;
    const back = (
      <Link className="gz-back" to={to("grades")} replace onClick={backToList}>
        <IconChevronLeft />
        Grades
      </Link>
    );
    if (!courses) return frame(<LoadFailed what="this class" onRetry={retry} />, back);
    if (!found) {
      return frame(
        <div className="gz-empty-state">
          <h2>That class isn't here</h2>
          <p>It may be from another year, or belong to another child.</p>
          <Link className="gz-btn" to={to("grades")} replace>
            All classes
          </Link>
        </div>,
        back,
      );
    }
    return frame(
      <ClassPage
        row={found.row}
        period={found.period}
        isCurrentPeriod={!found.period || found.period === currentPeriod}
        todo={todo}
        grades={grades}
        schedule={schedule}
        policy={latePolicies.find((p) => p.course_key === classKey) ?? null}
        postCount={(announcements ?? []).filter((a) => a.course_key === classKey).length}
        todayIso={todayIso}
        courseColors={courseColors}
        teachersTo={to("teachers", { class: classKey })}
        onOpen={setOpen}
        onToggle={toggleDone}
        onEditAppearance={() => setAppearanceFor(classKey)}
        onEditPolicy={() => setPolicyFor(classKey)}
      />,
      back,
    );
  }

  return frame(
    <>
      <header className="gz-title">
        <h1>{TABS.find((t) => t.tab === tab)!.label}</h1>
        <p>{purpose(tab, view, student.first_name, isStudent)}</p>
      </header>
      <div className="gz-content">
        {tab === "todo" ? (
          <TodoTab
            todo={todo}
            fresh={fresh}
            todayIso={todayIso}
            view={view}
            onView={saveView}
            onRetry={retry}
            onOpen={setOpen}
            onToggle={toggleDone}
            {...shared}
          />
        ) : tab === "schedule" ? (
          scheduleFailed ? (
            <LoadFailed what="the schedule" onRetry={retry} />
          ) : (
            <ScheduleTab schedule={schedule} rightNow={rightNow} grades={grades} todayIso={todayIso} now={now} {...shared} />
          )
        ) : !courses ? (
          <LoadFailed what={tab === "grades" ? "the classes" : "the teachers"} onRetry={retry} />
        ) : tab === "grades" ? (
          <GradesTab
            courses={courses}
            grades={grades}
            period={period}
            periods={periods}
            currentPeriod={currentPeriod}
            onPeriod={setPickedPeriod}
            classTo={(key) => to("grades", { class: key })}
            {...shared}
          />
        ) : (
          <TeachersTab
            announcements={announcements}
            courses={courses}
            todayIso={todayIso}
            onlyClass={classKey}
            allTo={to("teachers")}
            {...shared}
          />
        )}
      </div>
    </>,
  );
}

function LoadFailed({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className="gz-empty-state">
      <h2>Couldn't load {what}</h2>
      <p>Nothing is wrong with the schoolwork itself. Check the connection and try again.</p>
      <button type="button" className="gz-btn" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

/** Whose page this is. With more than one child it is also how to change that. */
function Who({ students, student, onSwitch }: { students: Student[]; student: Student | null; onSwitch: () => void }) {
  if (!student) return <span />;
  const inner = (
    <>
      <span className="gz-avatar" aria-hidden="true">
        {student.first_name.slice(0, 1).toUpperCase()}
      </span>
      {student.first_name}
    </>
  );
  if (students.length < 2) return <div className="gz-who">{inner}</div>;
  return (
    <button
      type="button"
      className="gz-who gz-switcher"
      aria-haspopup="dialog"
      aria-label={`Switch child, now showing ${student.first_name}`}
      onClick={onSwitch}
    >
      {inner}
      <IconChevronDown />
    </button>
  );
}

/** How current the page is, and the way into About this data. */
function Updated({ fresh, onOpen }: { fresh: Freshness | null; onOpen: () => void }) {
  const tone = !fresh || fresh.kind === "never" ? "plain" : fresh.kind === "stale" || fresh.needsLogin ? "stale" : "ok";
  const label = !fresh ? "About this data" : fresh.kind === "never" ? "Nothing sent yet" : `Updated ${fresh.ago}`;
  return (
    <button type="button" className={`gz-updated gz-is-${tone}`} aria-haspopup="dialog" onClick={onOpen}>
      {tone === "ok" && <IconCircleCheck />}
      {label}
    </button>
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
  else if (updated.due_date < localTodayIso()) next.missing = [updated, ...next.missing];
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
