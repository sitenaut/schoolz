import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { IconChevronLeft } from "../components/icons";
import { InviteShare } from "../components/InviteShare";
import { StudentLoginInvite } from "../components/StudentLoginInvite";
import type { School } from "../types";

type Student = {
  id: string;
  first_name: string;
  last_name: string;
  student_id: string;
  school_name: string | null;
  school_type: string | null;
  guardian_count: number;
  linked_via: string;
  matched_existing: boolean;
};

type PanelKind = "guardian" | "student" | "specials";
type Panel = { studentId: string; kind: PanelKind } | null;

export function ChildrenPage() {
  const [students, setStudents] = useState<Student[]>([]);
  const [schools, setSchools] = useState<School[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [studentId, setStudentId] = useState("");
  const [schoolId, setSchoolId] = useState("");

  const [panel, setPanel] = useState<Panel>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [studentsRes, schoolsRes] = await Promise.all([apiFetch("/students"), apiFetch("/schools")]);
      setStudents(studentsRes.ok ? await studentsRes.json() : []);
      setSchools(schoolsRes.ok ? await schoolsRes.json() : []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const addStudent = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    const res = await apiFetch("/students", {
      method: "POST",
      body: JSON.stringify({
        first_name: firstName,
        last_name: lastName,
        student_id: studentId,
        school_id: schoolId,
      }),
    });
    const body = await res.json();
    if (!res.ok) {
      setError(body.detail ?? "Could not add student");
      return;
    }
    setFirstName("");
    setLastName("");
    setStudentId("");
    setSchoolId("");
    if (body.matched_existing) {
      setNotice(
        `Linked to an existing student record shared by ${body.guardian_count - 1} other guardian(s) — they've been notified.`
      );
    }
    await load();
  };

  const removeStudent = async (id: string) => {
    if (!confirm("Remove this child from your profile? This only affects your own view.")) return;
    await apiFetch(`/students/${id}`, { method: "DELETE" });
    await load();
  };

  const toggle = (studentId: string, kind: PanelKind) =>
    setPanel((p) => (p && p.studentId === studentId && p.kind === kind ? null : { studentId, kind }));

  return (
    <div className="page page-narrow">
      <p>
        <Link to="/" className="back-link">
          <IconChevronLeft /> Home
        </Link>
      </p>
      <h1>My Children</h1>

      {notice && <div className="banner">{notice}</div>}
      {error && <div className="banner bad">{error}</div>}

      {loading ? (
        <p>Loading…</p>
      ) : students.length === 0 ? (
        <p className="note">
          No children on your profile yet. Were you sent an invite link? Open it and the child appears here on its own.
        </p>
      ) : (
        students.map((s) => {
          const open = panel?.studentId === s.id ? panel.kind : null;
          return (
            <div key={s.id} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <div>
                  <strong style={{ fontSize: 16 }}>
                    {s.first_name} {s.last_name}
                  </strong>
                  <div className="note" style={{ margin: "2px 0 0" }}>
                    ID {s.student_id}
                    {s.school_name && ` · ${s.school_name}`} · {s.guardian_count} guardian{s.guardian_count === 1 ? "" : "s"}
                  </div>
                </div>
                <Link to={`/kids/${s.id}`} className="btn sm">
                  Open
                </Link>
              </div>

              <div className="actions bare" style={{ flexWrap: "wrap", marginTop: 12 }}>
                {s.school_type === "elementary" && (
                  <button type="button" className={`btn ${open === "specials" ? "btn-primary" : ""}`} onClick={() => toggle(s.id, "specials")}>
                    Specials
                  </button>
                )}
                <button type="button" className={`btn ${open === "guardian" ? "btn-primary" : ""}`} onClick={() => toggle(s.id, "guardian")}>
                  Invite another guardian
                </button>
                <button type="button" className={`btn ${open === "student" ? "btn-primary" : ""}`} onClick={() => toggle(s.id, "student")}>
                  Give {s.first_name} their own login
                </button>
                <button type="button" className="btn subtle" onClick={() => removeStudent(s.id)}>
                  Remove from my profile
                </button>
              </div>

              {open === "specials" && (
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
                  <SpecialsEditor student={s} onClose={() => setPanel(null)} />
                </div>
              )}
              {open === "guardian" && (
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
                  <GuardianInvite student={s} onClose={() => setPanel(null)} />
                </div>
              )}
              {open === "student" && (
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
                  <StudentLoginInvite studentId={s.id} firstName={s.first_name} />
                </div>
              )}
            </div>
          );
        })
      )}

      <h2>Add a child</h2>
      <p className="note">
        Only needed for a child nobody has invited you to yet. If another parent already has them on schoolz, ask them
        for an invite instead - it links you to the same record with nothing to type.
      </p>
      <form onSubmit={addStudent}>
        <label>
          First name
          <input value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
        </label>
        <label>
          Last name
          <input value={lastName} onChange={(e) => setLastName(e.target.value)} required />
        </label>
        <label>
          Student ID
          <input value={studentId} onChange={(e) => setStudentId(e.target.value)} required />
        </label>
        <label>
          School
          <select value={schoolId} onChange={(e) => setSchoolId(e.target.value)} required>
            <option value="" disabled>
              Select a school…
            </option>
            {schools.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        {schools.length === 0 && (
          <p>
            No schools tracked yet — <Link to="/schools">add one first</Link>.
          </p>
        )}
        <button type="submit" className="btn btn-primary" disabled={schools.length === 0}>
          Add child
        </button>
      </form>
    </div>
  );
}

/** Share a child with another guardian (the other parent, a grandparent).
 * Accepting links them to this same Student row - they never re-type the
 * name, ID or school, so there's nothing to get wrong. */
function GuardianInvite({ student, onClose }: { student: Student; onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [invite, setInvite] = useState<{ link: string; email: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await apiFetch(`/students/${student.id}/invites`, {
        method: "POST",
        body: JSON.stringify({ invitee_email: email }),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body.detail ?? "Could not create invite");
        return;
      }
      setInvite({ link: body.accept_url, email: body.invitee_email });
    } finally {
      setBusy(false);
    }
  };

  if (invite) {
    return (
      <div>
        <p style={{ marginTop: 0 }}>Send this to {invite.email}:</p>
        <InviteShare
          link={invite.link}
          email={invite.email}
          subject={`Follow ${student.first_name} on schoolz`}
          body={`I added ${student.first_name} to schoolz - it pulls together school communications, assignments and grades. Open this link to see the same view I do:`}
        />
        <button type="button" className="btn sm" style={{ marginTop: 8 }} onClick={onClose}>
          Done
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={create} style={{ margin: 0 }}>
      <label style={{ marginBottom: 0 }}>
        Their email address
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required style={{ marginTop: 0 }} />
          <button type="submit" className="btn btn-primary" style={{ flex: "none" }} disabled={busy}>
            {busy ? "Creating…" : "Create invite"}
          </button>
        </div>
      </label>
      <p className="note" style={{ marginBottom: 0 }}>
        They can sign in with any account - the email is just so you both remember who it was for.
      </p>
      {error && <div className="banner bad" style={{ marginTop: 10 }}>{error}</div>}
    </form>
  );
}

type Special = { rotation_day: number; subject: string; teacher: string | null };

/** Which special (Art, PE, Music, …) this child has on each rotation day.
 * Shared with every guardian of the child; a blank day is "unknown". */
function SpecialsEditor({ student, onClose }: { student: Student; onClose: () => void }) {
  const [days, setDays] = useState<number[] | null>(null);
  const [rows, setRows] = useState<Record<number, { subject: string; teacher: string }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch(`/students/${student.id}/specials`)
      .then((r) => (r.ok ? r.json() : { rotation_days: [], specials: [] }))
      .then((d: { rotation_days: number[]; specials: Special[] }) => {
        setDays(d.rotation_days);
        setRows(Object.fromEntries(d.specials.map((s) => [s.rotation_day, { subject: s.subject, teacher: s.teacher ?? "" }])));
      });
  }, [student.id]);

  const set = (day: number, field: "subject" | "teacher", value: string) => {
    setSaved(false);
    setRows((cur) => ({ ...cur, [day]: { ...(cur[day] ?? { subject: "", teacher: "" }), [field]: value } }));
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = Object.entries(rows)
        .filter(([, r]) => r.subject.trim())
        .map(([day, r]) => ({ rotation_day: Number(day), subject: r.subject.trim(), teacher: r.teacher.trim() || null }));
      const res = await apiFetch(`/students/${student.id}/specials`, { method: "PUT", body: JSON.stringify(body) });
      if (!res.ok) {
        setError((await res.json()).detail ?? "Could not save");
        return;
      }
      setSaved(true);
    } finally {
      setBusy(false);
    }
  };

  if (days === null) return <p className="note">Loading…</p>;
  if (days.length === 0) {
    return <p className="note" style={{ margin: 0 }}>{student.school_name ?? "This school"} doesn't publish a day rotation we can match specials to yet.</p>;
  }

  return (
    <form onSubmit={save} style={{ margin: 0 }}>
      <p className="note" style={{ marginTop: 0 }}>
        What {student.first_name} has on each rotation day. Every guardian of {student.first_name} sees the same list. Leave a
        day blank if you don't know it.
      </p>
      <datalist id="specials-subjects">
        {["Art", "PE", "Music", "Computers", "Library", "STEM", "Spanish"].map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <div className="specials-grid">
        {days.map((day) => (
          <div className="specials-row" key={day}>
            <span className="specials-day">Day {day}</span>
            <input
              list="specials-subjects"
              placeholder="Special"
              aria-label={`Day ${day} special`}
              value={rows[day]?.subject ?? ""}
              onChange={(e) => set(day, "subject", e.target.value)}
              maxLength={100}
            />
            <input
              placeholder="Teacher (optional)"
              aria-label={`Day ${day} teacher`}
              value={rows[day]?.teacher ?? ""}
              onChange={(e) => set(day, "teacher", e.target.value)}
              maxLength={200}
            />
          </div>
        ))}
      </div>
      {error && <div className="banner bad" style={{ marginTop: 10 }}>{error}</div>}
      <div className="actions bare" style={{ marginTop: 10 }}>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Saving…" : "Save specials"}
        </button>
        <button type="button" className="btn" onClick={onClose}>
          {saved ? "Done" : "Cancel"}
        </button>
        {saved && <span className="note" style={{ margin: 0 }}>Saved</span>}
      </div>
    </form>
  );
}
