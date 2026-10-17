import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SeoHead } from "../../components/SeoHead";
import { IconChevronLeft, IconSearch, IconX } from "../../components/icons";
import { FilterSelect } from "../../components/ui/FilterSelect";
import { type ResourceType, categoryByKey, fetchResourceTypes } from "../../lib/localz";
import { useLocalzWhere } from "../../lib/localzWhere";
import { usePrerenderReady } from "../../lib/prerenderReady";
import { CategoryIcon } from "./CategoryIcon";
import { LocationButton } from "./LocationButton";
import { FitButton } from "./FitButton";
import { ResourceList } from "./ResourceList";
import { useResourceSearch } from "./useResourceSearch";

/** /localz/:category - every service of one kind, narrowed by the visitor's
 * location (Set my location: a county, kept on the device), kind of service
 * ("Food Pantries") and, optionally, a word. Keyed by category so switching
 * tabs starts with an empty search box. */
export function LocalzCategoryPage() {
  const { category: key } = useParams();
  return <CategoryView key={key} categoryKey={key} />;
}

function CategoryView({ categoryKey }: { categoryKey: string | undefined }) {
  const { t } = useTranslation();
  const category = categoryByKey(categoryKey);
  const county = useLocalzWhere()?.county ?? "";
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [types, setTypes] = useState<ResourceType[] | null>(null);
  // A type that no longer appears for the county/text picked since (no
  // soup kitchens listed in Sussex) stops filtering rather than showing an
  // empty list for a choice the dropdown no longer offers.
  const activeType = types === null || types.some((x) => x.code === type) ? type : "";
  const results = useResourceSearch({ category: category?.key, county, query, type: activeType, enabled: !!category });

  useEffect(() => {
    if (!category) return;
    let cancelled = false;
    fetchResourceTypes({ category: category.key, county: county || undefined, query: query || undefined }).then((rows) => {
      if (!cancelled) setTypes(rows);
    });
    return () => {
      cancelled = true;
    };
  }, [category, county, query]);

  useEffect(() => {
    const id = setTimeout(() => setQuery(draft.trim()), 400);
    return () => clearTimeout(id);
  }, [draft]);
  usePrerenderReady(!results.loading);

  if (!category) return <Navigate to="/localz" replace />;

  const label = t(category.label);

  return (
    <div>
      <SeoHead
        title={t("{{category}} help in New Jersey · Localz", { category: label })}
        description={t("{{blurb}} - free listings for every New Jersey county, with hours and phone numbers.", { blurb: t(category.blurb) })}
        path={`/localz/${category.key}`}
      />
      <div className="localz-nav-row">
        <Link className="localz-back-link" to="/localz">
          <IconChevronLeft />
          {t("All kinds of help")}
        </Link>
        <LocationButton />
      </div>
      <div className="localz-cat-head">
        <CategoryIcon category={category.key} className="localz-cat-icon" />
        <div>
          <h2>{label}</h2>
          <p className="localz-lede">{t(category.blurb)}</p>
        </div>
      </div>
      <div className="localz-fit-row">
        <FitButton />
      </div>

      <div className="localz-filters">
        <div className="search">
          <IconSearch />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("Search within {{category}}…", { category: label })}
            aria-label={t("Search within {{category}}", { category: label })}
            autoComplete="off"
            maxLength={100}
          />
          {draft && (
            <button className="search-clear" onClick={() => setDraft("")} aria-label={t("Clear search")}>
              <IconX />
            </button>
          )}
        </div>
        <FilterSelect
          value={activeType}
          onChange={setType}
          ariaLabel={t("Type of service")}
          placeholder={t("All types")}
          clearLabel={t("All types")}
          disabled={!types?.length}
          options={(types ?? []).map((x) => ({ value: x.code, label: x.name, hint: String(x.count) }))}
        />
      </div>

      {results.error ? (
        <p className="note">{t("Couldn't load these just now. Try again in a moment.")}</p>
      ) : results.loading && results.items.length === 0 ? (
        <div className="localz-list" aria-hidden="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <div className="localz-card skeleton" key={i}>
              <div className="shim line" style={{ width: "50%" }} />
              <div className="shim line" style={{ width: "75%", height: 10 }} />
            </div>
          ))}
        </div>
      ) : results.total === 0 ? (
        <p className="note">
          {query ? t("Nothing here matches \"{{query}}\".", { query }) : t("No listings here yet. We're adding more every week.")}{" "}
          <Link to="/localz">{t("See all kinds of help")}</Link>
        </p>
      ) : (
        <>
          <div className="dir-count">{results.total === 1 ? t("1 listing") : t("{{total}} listings", { total: results.total })}</div>
          <ResourceList items={results.items} busy={results.loading} />
          {results.hasMore && (
            <button className="btn localz-more" onClick={results.loadMore} disabled={results.loading}>
              {t("Show more")}
            </button>
          )}
        </>
      )}
    </div>
  );
}
