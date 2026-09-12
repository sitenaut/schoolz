import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import { useMySchools } from "../lib/mySchools";
import { usePrerenderReady } from "../lib/prerenderReady";
import { IconSearch } from "../components/icons";
import { SeoHead } from "../components/SeoHead";
import { SCHOOL_TYPE_TIERS } from "../lib/schoolType";
import type { School } from "../types";

export function SchoolsPage() {
  const { user } = useAuth();
  const { allSchools, activeSchools, loading } = useMySchools();
  usePrerenderReady(!loading);
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

  // Grouped by tier (elementary/middle/high/...) like the /start picker,
  // instead of one long alphabetical-ish list - easier to scan when a
  // visitor knows roughly what kind of school they're after.
  const groups = useMemo(
    () =>
      SCHOOL_TYPE_TIERS.map((t) => ({ ...t, schools: schools.filter((s) => (s.school_type ?? "other") === t.key) })).filter(
        (g) => g.schools.length > 0,
      ),
    [schools],
  );

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
      <SeoHead
        title="Cherry Hill schools directory · schoolz"
        description="Browse every Cherry Hill Public Schools elementary, middle, and high school, plus tracked local preschools - addresses, phone numbers, and websites."
        path="/schools"
      />
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
        // Same tile-grid look as the /start picker (.sgrid/.sopt) - this
        // page still navigates to a school's own page on click rather
        // than toggling a pick, so no checkbox box, just the card.
        groups.map((g) => (
          <div key={g.key}>
            <div className="tier">{g.label}</div>
            <div className="sgrid">
              {g.schools.map((s) => (
                <Link className="sopt" to={`/schools/${s.slug}`} key={s.id}>
                  {s.logo_url ? <img className="sopt-logo" src={s.logo_url} alt="" /> : null}
                  {s.short_name || s.name}
                </Link>
              ))}
            </div>
          </div>
        ))
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
