import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { apiFetch } from "../api";
import { IconChevronLeft, IconUsers } from "../components/icons";
import { useAuth } from "../context/AuthContext";

type Student = {
  id: string;
  first_name: string;
  last_name: string;
  student_id: string;
  school_name: string | null;
};

// Lists the guardian's own linked students as entry points into their
// Backpack Capture data (schedule/assignments). This is deliberately a
// separate page from /children (which is about adding/removing/inviting
// guardians to a student) - Kids is about *viewing* what's been imported
// for a student already on the guardian's profile, not managing the link
// itself. A student's own login has exactly one student - itself - so it
// skips the list and lands on its own view.
export function KidsPage() {
  const { user } = useAuth();
  const [students, setStudents] = useState<Student[]>([]);
  const [loading, setLoading] = useState(true);
  const isStudent = Boolean(user?.student_profile_id);

  useEffect(() => {
    if (isStudent) return;
    apiFetch("/students")
      .then((res) => (res.ok ? res.json() : []))
      .then(setStudents)
      .finally(() => setLoading(false));
  }, [isStudent]);

  if (isStudent) return <Navigate to={`/kids/${user!.student_profile_id}`} replace />;

  return (
    <div className="page">
      <Link to="/" className="back-link">
        <IconChevronLeft /> Home
      </Link>
      <div className="eyebrow">Backpack Capture</div>
      <h1>Kids</h1>
      <p className="note">
        Each child's schedule, assignments, and grades here come from your own Backpack Capture exports (the browser
        extension that reads Classroom/Genesis pages you're already logged into) — nothing here is fetched
        automatically or shared with anyone outside your family.
      </p>

      {loading ? (
        <p className="note">Loading…</p>
      ) : students.length === 0 ? (
        <div className="empty">
          No children on your profile yet — <Link to="/children">add one first</Link>.
        </div>
      ) : (
        <ul className="item-list">
          {students.map((s) => (
            <li key={s.id} className="item-card">
              <Link to={`/kids/${s.id}`} style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
                <IconUsers className="kids-icon-md" />
                <span>
                  <span className="item-title" style={{ display: "block" }}>
                    {s.first_name} {s.last_name}
                  </span>
                  {s.school_name && <span className="item-desc">{s.school_name}</span>}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <style>{".kids-icon-md { width: 22px; height: 22px; color: var(--primary); flex: none; }"}</style>
    </div>
  );
}
