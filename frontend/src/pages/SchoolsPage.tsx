import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import type { School } from "../types";

export function SchoolsPage() {
  const { user } = useAuth();
  // "My Schools" only makes sense for a logged-in guardian with linked
  // kids - an anonymous visitor (this whole page is public) starts on the
  // full directory instead.
  const [tab, setTab] = useState<"mine" | "all">(user ? "mine" : "all");
  const [schools, setSchools] = useState<School[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    apiFetch(tab === "mine" ? "/schools/mine" : "/schools")
      .then((r) => (r.ok ? r.json() : []))
      .then(setSchools);
  };

  useEffect(load, [tab]);

  const addSchool = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const res = await apiFetch("/schools", { method: "POST", body: JSON.stringify({ name }) });
    const body = await res.json();
    if (!res.ok) {
      setError(body.detail ?? "Could not add school");
      return;
    }
    setName("");
    setTab("all");
    load();
  };

  return (
    <div>
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>All schools</h2>
        <Link to="/start">Pick mine</Link>
      </div>

      <div className="tabs">
        {user && (
          <button className={`tab ${tab === "mine" ? "active" : ""}`} onClick={() => setTab("mine")}>
            My Children's Schools
          </button>
        )}
        <button className={`tab ${tab === "all" ? "active" : ""}`} onClick={() => setTab("all")}>
          All schools
        </button>
      </div>

      {schools.length === 0 ? (
        <p>
          {tab === "mine"
            ? "This tab shows schools your added children attend (via the \"My Children\" page) — that's separate from the schools you picked in \"My schools\" at the top of the app. Add a child once their school is listed below, or switch to \"All schools\" to browse."
            : "No schools tracked yet — add one below."}
        </p>
      ) : (
        <ul className="school-list">
          {schools.map((s) => (
            <li key={s.id}>
              <Link to={`/schools/${s.slug}`} className="school-list-item">
                <div>
                  <span className="school-name-row">
                    {s.logo_url && <img className="school-list-logo" src={s.logo_url} alt="" />}
                    <strong>{s.name}</strong>
                  </span>
                  {s.address && <div className="item-desc">{s.address}</div>}
                </div>
                <span>&rarr;</span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {user?.is_admin && (
        <>
          <div className="section-title">Add a school</div>
          {error && <p style={{ color: "var(--color-danger)" }}>{error}</p>}
          <form onSubmit={addSchool} className="card">
            <label>
              School name
              <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Bret Harte Elementary" />
            </label>
            <button type="submit" className="btn btn-primary">
              Add school
            </button>
          </form>
        </>
      )}
    </div>
  );
}
