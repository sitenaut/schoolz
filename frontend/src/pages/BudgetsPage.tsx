import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../api";
import { pct } from "../components/BudgetSection";
import { IconSearch } from "../components/icons";
import { SeoHead } from "../components/SeoHead";
import { foldAccents } from "../lib/i18n";
import { usePrerenderReady } from "../lib/prerenderReady";
import type { BudgetIndex } from "../types";

/** /budgets: every New Jersey school district's budget, found by name or
 * county. Each row links to the district's own page; the districts schoolz
 * tracks are marked, since those also have school pages here. Listed in full
 * (grouped by county, never collapsed), so every district page is one link
 * from here for a visitor and a crawler alike. */
export function BudgetsPage() {
  const { t } = useTranslation();
  const [index, setIndex] = useState<BudgetIndex | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let current = true;
    apiFetch("/budgets")
      .then((r) => {
        if (!r.ok) throw new Error(`budgets ${r.status}`);
        return r.json() as Promise<BudgetIndex>;
      })
      .then(
        (data) => current && (setIndex(data), setFailed(false)),
        () => current && setFailed(true),
      );
    return () => {
      current = false;
    };
  }, [attempt]);
  usePrerenderReady(!!index);

  const counties = useMemo(() => {
    const q = foldAccents(query.trim());
    const byCounty = new Map<string, BudgetIndex["districts"]>();
    for (const d of index?.districts ?? []) {
      if (q && !foldAccents(d.name).includes(q) && !foldAccents(d.county ?? "").includes(q)) continue;
      const county = d.county ?? "";
      byCounty.set(county, [...(byCounty.get(county) ?? []), d]);
    }
    return [...byCounty.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [index, query]);

  const year = index?.budget_year;
  return (
    <div>
      <SeoHead
        title={t("New Jersey school district budgets{{year}} · schoolz", { year: year ? ` ${year}` : "" })}
        description={t(
          "Look up any New Jersey school district's budget: employee benefits, state aid, the local school tax levy, health insurance costs and class sizes, from the state's own files.",
        )}
        path="/budgets"
      />
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>{t("District budgets")}</h2>
        <Link to="/schools">{t("Schools")}</Link>
      </div>
      <p className="note" style={{ marginTop: 0 }}>
        {year
          ? t(
              "Every New Jersey school district's {{year}} budget, from New Jersey Department of Education files. Budgets are set for a whole district, so every school in a district shares its figures.",
              { year },
            )
          : t("Every New Jersey school district's budget, from New Jersey Department of Education files.")}
      </p>

      <div className="search" style={{ margin: "0.75rem 0" }}>
        <IconSearch />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("Search by district or county…")}
          aria-label={t("Search by district or county")}
        />
      </div>

      {failed ? (
        <div className="empty">
          <p>{t("Couldn't load the district budgets just now.")}</p>
          <button type="button" className="btn" onClick={() => setAttempt((n) => n + 1)}>
            {t("Try again")}
          </button>
        </div>
      ) : !index ? (
        <p className="note">{t("Loading…")}</p>
      ) : counties.length === 0 ? (
        <p>{query.trim() ? t("No districts match \"{{q}}\".", { q: query.trim() }) : t("No district budgets yet.")}</p>
      ) : (
        counties.map(([county, districts]) => (
          <section key={county} className="budget-county">
            <div className="tier">{county ? t("{{county}} County", { county }) : t("Other")}</div>
            <ul className="budget-list">
              {districts.map((d) => (
                <li key={d.slug}>
                  <Link to={`/budgets/${d.slug}`}>{d.name}</Link>
                  {d.tracked && <span className="tag">{t("On schoolz")}</span>}
                  <span className="note">
                    {[
                      d.levy_change_pct != null && t("Tax levy {{pct}}", { pct: pct(d.levy_change_pct) }),
                      d.benefits_change_pct != null && t("Benefits {{pct}}", { pct: pct(d.benefits_change_pct) }),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
