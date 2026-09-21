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
  guardian_count: number;
  linked_via: string;
  matched_existing: boolean;
};

type Panel = { studentId: string; kind: "guardian" | "student" } | null;

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

  const toggle = (studentId: string, kind: "guardian" | "student") =>
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
