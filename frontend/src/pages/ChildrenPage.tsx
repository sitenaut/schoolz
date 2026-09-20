import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { IconChevronLeft } from "../components/icons";
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

  const [inviteFor, setInviteFor] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteLink, setInviteLink] = useState<string | null>(null);

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

  const sendInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteFor) return;
    setError(null);
    const res = await apiFetch(`/students/${inviteFor}/invites`, {
      method: "POST",
      body: JSON.stringify({ invitee_email: inviteEmail }),
    });
    const body = await res.json();
    if (!res.ok) {
      setError(body.detail ?? "Could not create invite");
      return;
    }
    setInviteLink(body.accept_url);
  };

  const closeInvite = () => {
    setInviteFor(null);
    setInviteEmail("");
    setInviteLink(null);
  };

  return (
    <div style={{ maxWidth: 560, margin: "3rem auto", fontFamily: "sans-serif" }}>
      <p>
        <Link to="/" className="back-link">
          <IconChevronLeft /> Home
        </Link>
      </p>
      <h1>My Children</h1>

      {notice && <p style={{ color: "green" }}>{notice}</p>}
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {loading ? (
        <p>Loading…</p>
      ) : students.length === 0 ? (
        <p>No children on your profile yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {students.map((s) => (
            <li key={s.id} style={{ border: "1px solid #ccc", borderRadius: 6, padding: "0.75rem", marginBottom: "0.5rem" }}>
              <strong>
                {s.first_name} {s.last_name}
              </strong>{" "}
              (ID {s.student_id}){s.school_name && ` — ${s.school_name}`}
              <br />
              <small>
                {s.guardian_count} guardian{s.guardian_count === 1 ? "" : "s"} · added via {s.linked_via.replace("_", " ")}
              </small>
              <br />
              <button onClick={() => setInviteFor(s.id)} style={{ marginTop: "0.5rem", marginRight: "0.5rem" }}>
                Invite another guardian
              </button>
              {/* The student's OWN login is a separate, stricter invite
                  (routers/student_accounts.py) - the form for it lives on
                  the Kids detail page (student.viewer_role === "guardian"
                  gates it there), not duplicated here. This used to be
                  reachable from the main nav's "Kids" link; once that got
                  renamed to "Gradez" and repointed at /focus/, ordinary
                  (non-admin) guardians had no way to reach it at all - the
                  only remaining path was /admin/kids, which requires
                  is_admin. This link is what makes it reachable again for
                  everyone, not just admins. */}
              <Link
                to={`/kids/${s.id}`}
                className="ghost"
                style={{ marginTop: "0.5rem", marginRight: "0.5rem", display: "inline-block" }}
              >
                Give {s.first_name} their own login
              </Link>
              <button onClick={() => removeStudent(s.id)}>Remove from my profile</button>
            </li>
          ))}
        </ul>
      )}

      <h2>Add a child</h2>
      <form onSubmit={addStudent}>
        <label>
          First name
          <input value={firstName} onChange={(e) => setFirstName(e.target.value)} required />
        </label>
        <br />
        <label>
          Last name
          <input value={lastName} onChange={(e) => setLastName(e.target.value)} required />
        </label>
        <br />
        <label>
          Student ID
          <input value={studentId} onChange={(e) => setStudentId(e.target.value)} required />
        </label>
        <br />
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
        <br />
        <button type="submit" disabled={schools.length === 0}>
          Add child
        </button>
      </form>

      {inviteFor && (
        <div style={{ marginTop: "1.5rem", border: "1px solid #ccc", borderRadius: 6, padding: "1rem" }}>
          <h3>Invite a guardian</h3>
          {inviteLink ? (
            <>
              <p>Send this link to the person you're inviting:</p>
              <input readOnly value={inviteLink} style={{ width: "100%" }} onFocus={(e) => e.target.select()} />
              <br />
              <button onClick={closeInvite} style={{ marginTop: "0.5rem" }}>
                Done
              </button>
            </>
          ) : (
            <form onSubmit={sendInvite}>
              <label>
                Their email
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  required
                />
              </label>
              <br />
              <button type="submit">Create invite</button>
              <button type="button" onClick={closeInvite} style={{ marginLeft: "0.5rem" }}>
                Cancel
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
