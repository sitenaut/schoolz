import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import { useMySchools } from "../lib/mySchools";
import { IconChevronRight, IconSearch } from "../components/icons";
import type { School } from "../types";

export function SchoolsPage() {
  const { user } = useAuth();
  const { allSchools, activeSchools } = useMySchools();
  // "My schools" reflects exactly the top ribbon's current picks/filter -
  // there's no separate "linked children" concept here anymore. That used
  // to be a second, differently-scoped "My Schools" tab (-> GET
  // /schools/mine, keyed off added children, not the ribbon) that read as
  // "my picks aren't registering" to anyone who'd only used the /start
  // picker and never added a child.
  const [tab, setTab] = useState<"mine" | "all">(activeSchools.length > 0 ? "mine" : "all");
  const [query, setQuery] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [allSchoolsAfterAdd, setAllSchoolsAfterAdd] = useState<School[] | null>(null);

  const baseList = tab === "mine" ? activeSchools : (allSchoolsAfterAdd ?? allSchools);
  const schools = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return baseList;
    return baseList.filter((s) => s.name.toLowerCase().includes(q) || (s.short_name ?? "").toLowerCase().includes(q));
  }, [baseList, query]);

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
    const fresh = await apiFetch("/schools");
    setAllSchoolsAfterAdd(fresh.ok ? await fresh.json() : null);
  };

  return (
    <div>
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>Schools</h2>
        <Link to="/start">Manage my schools</Link>
      </div>

      <div className="tabs">
        {activeSchools.length > 0 && (
          <button className={`tab ${tab === "mine" ? "active" : ""}`} onClick={() => setTab("mine")}>
            My schools
          </button>
        )}
        <button className={`tab ${tab === "all" ? "active" : ""}`} onClick={() => setTab("all")}>
          All schools
        </button>
      </div>

      <div className="search" style={{ margin: "0.75rem 0" }}>
        <IconSearch />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search schools by name…"
          aria-label="Search schools by name"
        />
      </div>

      {schools.length === 0 ? (
        <p>
          {query.trim() ? (
            `No schools match "${query.trim()}".`
          ) : tab === "mine" ? (
            <>
              You haven't picked any schools yet. <Link to="/start">Pick some</Link> to see them here.
            </>
          ) : (
            "No schools tracked yet — add one below."
          )}
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
                <IconChevronRight className="trailing-chevron" />
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
