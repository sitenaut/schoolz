import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { errorDetail } from "../lib/errorDetail";
import type { School } from "../types";
import { InviteShare } from "./InviteShare";
import { FilterSelect } from "./ui/FilterSelect";

type ChildRef = { id: string; first_name: string; school_name: string | null };

/** Share a child with another guardian (the other parent, a grandparent).
 * Accepting links them to this same Student row - they never re-type the
 * name, ID or school, so there's nothing to get wrong. */
export function GuardianInvite({ student, onClose }: { student: ChildRef; onClose: () => void }) {
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
        setError(errorDetail(body, "Could not create invite"));
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
export function SpecialsEditor({ student, onClose }: { student: ChildRef; onClose: () => void }) {
  const [days, setDays] = useState<number[] | null>(null);
  const [letters, setLetters] = useState(false);
  const [rows, setRows] = useState<Record<number, { subject: string; teacher: string }>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch(`/students/${student.id}/specials`)
      .then((r) => (r.ok ? r.json() : { rotation_days: [], specials: [] }))
      .then((d: { rotation_days: number[]; rotation_letters?: boolean; specials: Special[] }) => {
        setDays(d.rotation_days);
        setLetters(!!d.rotation_letters);
        setRows(Object.fromEntries(d.specials.map((s) => [s.rotation_day, { subject: s.subject, teacher: s.teacher ?? "" }])));
      });
  }, [student.id]);

  // A school that names its days A-F stores them as 1-6.
  const dayName = (day: number) => (letters ? String.fromCharCode(64 + day) : String(day));

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
        setError(errorDetail(await res.json().catch(() => null), "Could not save"));
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
            <span className="specials-day">Day {dayName(day)}</span>
            <input
              list="specials-subjects"
              placeholder="Special"
              aria-label={`Day ${dayName(day)} special`}
              value={rows[day]?.subject ?? ""}
              onChange={(e) => set(day, "subject", e.target.value)}
              maxLength={100}
            />
            <input
              placeholder="Teacher (optional)"
              aria-label={`Day ${dayName(day)} teacher`}
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

/** Add a child nobody has invited this guardian to yet. A match on name +
 * student ID links to the existing record (and tells its other guardians). */
export function AddChildForm({ onAdded, onCancel }: { onAdded: (notice: string | null) => void; onCancel?: () => void }) {
  const [schools, setSchools] = useState<School[] | null>(null);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [studentId, setStudentId] = useState("");
  const [schoolId, setSchoolId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiFetch("/schools")
      .then((r) => (r.ok ? r.json() : []))
      .then(setSchools);
  }, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await apiFetch("/students", {
        method: "POST",
        body: JSON.stringify({ first_name: firstName, last_name: lastName, student_id: studentId, school_id: schoolId }),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(errorDetail(body, "Could not add student"));
        return;
      }
      onAdded(
        body.matched_existing
          ? `Linked to an existing student record shared by ${body.guardian_count - 1} other guardian(s) — they've been notified.`
          : null,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={add} style={{ margin: 0 }}>
      <p className="note" style={{ marginTop: 0 }}>
        Only needed for a child nobody has invited you to yet. If another parent already has them on schoolz, ask them for an
        invite instead - it links you to the same record with nothing to type.
      </p>
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
        <FilterSelect
          value={schoolId}
          onChange={setSchoolId}
          options={(schools ?? []).map((s) => ({ value: s.id, label: s.name }))}
          placeholder="Select a school…"
          required
        />
      </label>
      {schools !== null && schools.length === 0 && (
        <p>
          No schools tracked yet — <Link to="/schools">add one first</Link>.
        </p>
      )}
      {error && <div className="banner bad">{error}</div>}
      <div className="actions bare">
        <button type="submit" className="btn btn-primary" disabled={busy || !schools?.length}>
          {busy ? "Adding…" : "Add child"}
        </button>
        {onCancel && (
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
