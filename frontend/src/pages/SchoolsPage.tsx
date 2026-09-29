import { can } from "../lib/permissions";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { foldAccents } from "../lib/i18n";
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
  const { t } = useTranslation();
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
    const q = foldAccents(query.trim());
    if (!q) return baseList;
    return baseList.filter((s) => foldAccents(s.name).includes(q) || foldAccents(s.short_name ?? "").includes(q));
  }, [baseList, query]);

  // Grouped by tier (elementary/middle/high/...) like the /start picker,
  // instead of one long alphabetical-ish list - easier to scan when a
  // visitor knows roughly what kind of school they're after.
  const groups = useMemo(
    () =>
      SCHOOL_TYPE_TIERS.map((tier) => ({ ...tier, schools: schools.filter((s) => (s.school_type ?? "other") === tier.key) })).filter(
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
        title={t("{{towns}} schools directory · schoolz", { towns: townsLabel(myTowns) })}
        description={t("Browse every {{towns}} public elementary, middle, and high school, plus tracked local preschools - addresses, phone numbers, and websites.", { towns: townsLabel(myTowns) })}
        path="/schools"
      />
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>{t("Schools")}</h2>
        <Link to="/start">{t("Manage my schools")}</Link>
      </div>

      <div className="tabs">
        {activeSchools.length > 0 && (
          <button className={`tab ${tab === "mine" ? "active" : ""}`} onClick={() => setTab("mine")}>
            {t("My schools")}
          </button>
        )}
        <button className={`tab ${tab === "all" ? "active" : ""}`} onClick={() => setTab("all")}>
          {t("All schools")}
        </button>
      </div>

      <div className="search" style={{ margin: "0.75rem 0" }}>
        <IconSearch />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("Search schools by name…")}
          aria-label={t("Search schools by name")}
        />
      </div>

      {schools.length === 0 ? (
        <p>
          {query.trim() ? (
            t("No schools match \"{{q}}\".", { q: query.trim() })
          ) : tab === "mine" ? (
            <>
              {t("You haven't picked any schools yet.")} <Link to="/start">{t("Pick some")}</Link> {t("to see them here.")}
            </>
          ) : (
            t("No schools tracked yet — add one below.")
          )}
        </p>
      ) : (
        // Same tile-grid look as the /start picker (.sgrid/.sopt) - this
        // page still navigates to a school's own page on click rather
        // than toggling a pick, so no checkbox box, just the card.
        groups.map((g) => (
          <div key={g.key}>
            <div className="tier">{t(g.label)}</div>
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

      {can(user, "schools.manage") && (
        <>
          <div className="section-title">{t("Add a school")}</div>
          {error && <p style={{ color: "var(--color-danger)" }}>{error}</p>}
          <form onSubmit={addSchool} className="card">
            <label>
              {t("School name")}
              <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Bret Harte Elementary" />
            </label>
            <button type="submit" className="btn btn-primary">
              {t("Add school")}
            </button>
          </form>
        </>
      )}
    </div>
  );
}
