import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import { logoClass } from "../lib/logos";
import { useMySchools } from "../lib/mySchools";
import { townsLabel } from "../lib/towns";
import { usePrerenderReady } from "../lib/prerenderReady";
import { IconSearch } from "../components/icons";
import { SeoHead } from "../components/SeoHead";
import { SCHOOL_TYPE_TIERS } from "../lib/schoolType";
import type { School, SchoolClassYear } from "../types";

export function SchoolsPage() {
  const { user } = useAuth();
  const { allSchools, activeSchools, loading, myTowns } = useMySchools();
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

  // A high school's class chips, shown inline on its tile so a parent can
  // jump straight to "Class of 2029" without a stop at the school page
  // first. Fetched only for the high schools actually in view (a bounded,
  // small set - a district has a handful at most).
  const [classYearsBySlug, setClassYearsBySlug] = useState<Record<string, SchoolClassYear[]>>({});
  const highSchoolSlugs = useMemo(() => schools.filter((s) => s.school_type === "high").map((s) => s.slug).join(","), [schools]);
  useEffect(() => {
    if (!highSchoolSlugs) return;
    let cancelled = false;
    Promise.all(
      highSchoolSlugs.split(",").map((slug) => apiFetch(`/schools/${slug}/class-years`).then((r) => (r.ok ? r.json() : []))),
    ).then((results) => {
      if (cancelled) return;
      const bySlug: Record<string, SchoolClassYear[]> = {};
      highSchoolSlugs.split(",").forEach((slug, i) => (bySlug[slug] = results[i]));
      setClassYearsBySlug(bySlug);
    });
    return () => {
      cancelled = true;
    };
  }, [highSchoolSlugs]);

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
        title={`${townsLabel(myTowns)} schools directory · schoolz`}
        description={`Browse every ${townsLabel(myTowns)} public elementary, middle, and high school, plus tracked local preschools - addresses, phone numbers, and websites.`}
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
                <div key={s.id}>
                  <Link className="sopt" to={`/schools/${s.slug}`}>
                    {s.logo_url ? <img className={logoClass("sopt-logo", s.slug)} src={s.logo_url} alt="" /> : null}
                    {s.short_name || s.name}
                  </Link>
                  {(classYearsBySlug[s.slug]?.length ?? 0) > 0 && (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                      {classYearsBySlug[s.slug].map((c) => (
                        <Link key={c.grad_year} className="tag" style={{ textDecoration: "none" }} to={`/schools/${s.slug}/class-of-${c.grad_year}`}>
                          {c.grad_year}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
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
