import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SeoHead } from "../../components/SeoHead";
import { IconNeighbors, IconSearch, IconX } from "../../components/icons";
import { LOCALZ_CATEGORIES, type ResourceCategoryCount, fetchResourceCategories } from "../../lib/localz";
import { useLocalzScope } from "../../lib/localzWhere";
import { usePrerenderReady } from "../../lib/prerenderReady";
import { CategoryIcon } from "./CategoryIcon";
import { LocationButton } from "./LocationButton";
import { RadiusChips, RadiusNote } from "./RadiusChips";
import { FitButton } from "./FitButton";
import { ResourceList } from "./ResourceList";
import { useResourceSearch } from "./useResourceSearch";

/** /localz - search, or pick a kind of help. Search runs on submit, not per
 * keystroke: a half-typed word is no use to anyone, and the text never goes
 * in the URL (see lib/localz.ts). */
export function LocalzHomePage() {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [counts, setCounts] = useState<Map<string, number> | null>(null);
  const scope = useLocalzScope();
  const county = scope.county;
  const results = useResourceSearch({ query, scope, enabled: !!query });

  useEffect(() => {
    let cancelled = false;
    fetchResourceCategories(county || undefined).then((rows: ResourceCategoryCount[]) => {
      if (!cancelled) setCounts(new Map(rows.map((r) => [r.key, r.count])));
    });
    return () => {
      cancelled = true;
    };
  }, [county]);
  usePrerenderReady(counts !== null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQuery(draft.trim());
  };
  const clear = () => {
    setDraft("");
    setQuery("");
  };

  return (
    <div>
      <SeoHead
        title={t("Find help in New Jersey: food, housing, health · Localz")}
        description={t("Food pantries, help with rent and utilities, clinics, child care and more across New Jersey. Free to use, no account needed.")}
        path="/localz"
      />
      <div className="localz-nav-row">
        <h2 className="localz-title">
          {scope.near ? t("Find help near you") : county ? t("Find help in {{county}} County", { county }) : t("Find help in New Jersey")}
        </h2>
        <LocationButton />
      </div>
      <p className="localz-lede">{t("Food, housing, health and more across New Jersey. Free to use, and nothing here needs an account.")}</p>
      <div className="localz-fit-row">
        <FitButton />
      </div>

      <form className="search localz-search" role="search" onSubmit={submit}>
        <IconSearch />
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("What do you need help with?")}
          aria-label={t("Search for help")}
          autoComplete="off"
          enterKeyHint="search"
          maxLength={100}
        />
        {draft && (
          <button type="button" className="search-clear" onClick={clear} aria-label={t("Clear search")}>
            <IconX />
          </button>
        )}
        <button type="submit" className="btn btn-primary localz-search-go">
          {t("Search")}
        </button>
      </form>
      <RadiusChips />

      {query ? (
        <section aria-live="polite">
          {results.error ? (
            <p className="note">{t("Couldn't search just now. Try again in a moment.")}</p>
          ) : results.loading && results.items.length === 0 ? (
            <p className="note">{t("Searching…")}</p>
          ) : results.total === 0 ? (
            <p className="note">{t("Nothing matched \"{{query}}\". Try a simpler word, or pick a kind of help below.", { query })}</p>
          ) : (
            <>
              <div className="dir-count">{results.total === 1 ? t("1 result") : t("{{total}} results", { total: results.total })}</div>
              {scope.near && <RadiusNote miles={scope.near.miles} />}
              <ResourceList items={results.items} />
              {results.hasMore && (
                <button className="btn localz-more" onClick={results.loadMore} disabled={results.loading}>
                  {t("Show more")}
                </button>
              )}
            </>
          )}
          <button className="btn ghost localz-back" onClick={clear}>
            {t("Back to all kinds of help")}
          </button>
        </section>
      ) : (
        <nav className="localz-tiles" aria-label={t("Kinds of help")}>
          {LOCALZ_CATEGORIES.map((c) => (
            <Link key={c.key} to={`/localz/${c.key}`} className="localz-tile">
              <CategoryIcon category={c.key} />
              <span className="localz-tile-label">{t(c.label)}</span>
              <span className="localz-tile-blurb">{t(c.blurb)}</span>
              {counts?.get(c.key) ? (
                <span className="localz-tile-count">{counts.get(c.key) === 1 ? t("1 listing") : t("{{total}} listings", { total: counts.get(c.key) })}</span>
              ) : null}
            </Link>
          ))}
          <Link to="/localz/bills" className="localz-tile">
            <IconNeighbors />
            <span className="localz-tile-label">{t("Neighborz")}</span>
            <span className="localz-tile-blurb">{t("Neighbors paying each other's utility bills")}</span>
          </Link>
        </nav>
      )}

      <p className="localz-footnote">
        {t("Listings come from NJ 211 and the organizations themselves. Hours change - calling ahead is always a good idea.")}{" "}
        <Link to="/contact">{t("Something wrong or missing? Tell us.")}</Link>{" "}
        <Link to="/localz/providers">{t("Run a program? List it here.")}</Link>
      </p>
    </div>
  );
}
