import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { apiFetch } from "../api";
import { telHref } from "../lib/calendar";
import { logoClass } from "../lib/logos";
import { useMySchools } from "../lib/mySchools";
import { townsLabel } from "../lib/towns";
import { usePrerenderReady } from "../lib/prerenderReady";
import { trackEvent } from "../lib/track";
import { SeoHead } from "../components/SeoHead";
import { IconChevronLeft, IconChevronRight, IconMail, IconPhone, IconSearch, IconX } from "../components/icons";
import { SCHOOL_TYPE_TIERS } from "../lib/schoolType";
import type { DirectoryPage as DirectoryPageData } from "../types";

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 300;

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0];
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

/** Every staff member in the district in one searchable list.
 *
 * The per-school page already has a "Full staff directory" accordion, but
 * that only helps a parent who already knows which school the person they
 * want is at - the actual question is usually "who is the middle-school
 * nurse" or "what's Mr Whoever's email", with the school being the thing
 * they're unsure about. So this searches all ~1900 people at once and
 * treats the school as a filter rather than the entry point.
 *
 * Searching, filtering and paging are all server-side (GET
 * /directory/staff): the full list is a few hundred KB of JSON, which is
 * not something to hand a phone on a school-morning connection just so
 * the filtering can happen in the browser.
 *
 * Scoped to the visitor's own districts (those of the schools they picked,
 * or their children's): a Cherry Hill parent has no use for the other
 * districts' people, and not loading them is most of the page's weight.
 * Nothing picked, or a picked school with no district, shows everyone. */
export function DirectoryPage() {
  const { t } = useTranslation();
  const { allSchools, myTowns, mySchools, loading: schoolsLoading } = useMySchools();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [school, setSchool] = useState("");
  const [category, setCategory] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<DirectoryPageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // Sorted and joined so the effect below re-runs on a change of districts,
  // not on every new array the provider builds.
  const districtKey = useMemo(() => {
    if (mySchools.length === 0 || mySchools.some((s) => !s.district_id)) return "";
    return [...new Set(mySchools.map((s) => s.district_id as string))].sort().join(",");
  }, [mySchools]);

  // Same 300ms settle as the calendar's search box - a query per keystroke
  // against 1900 rows is pointless churn, and the chip counts visibly
  // flickering as you type reads as the page glitching.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setOffset(0);
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  // Responses can land out of order once a filter changes mid-flight (the
  // abort covers the common case, but a response already in the pipe still
  // resolves), so only the newest request is allowed to paint.
  const reqId = useRef(0);
  useEffect(() => {
    // Until the picked schools are known, an unscoped request would load the
    // very people this page is meant not to.
    if (schoolsLoading) return;
    const controller = new AbortController();
    const id = ++reqId.current;
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    for (const d of districtKey ? districtKey.split(",") : []) params.append("district_id", d);
    if (query.trim()) params.set("q", query.trim());
    if (school) params.set("school_id", school);
    if (category) params.set("category", category);
    apiFetch(`/directory/staff?${params.toString()}`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body: DirectoryPageData) => {
        if (id !== reqId.current) return;
        setData(body);
        setError(false);
        setLoading(false);
      })
      .catch(() => {
        if (id !== reqId.current || controller.signal.aborted) return;
        setError(true);
        setLoading(false);
      });
    return () => controller.abort();
  }, [query, school, category, offset, districtKey, schoolsLoading]);

  usePrerenderReady(!loading);

  useEffect(() => {
    const q = query.trim();
    if (q.length >= 2) trackEvent("directory_search", { has_school: String(!!school), has_category: String(!!category) });
  }, [query, school, category]);

  const schoolsBySlug = useMemo(() => new Map(allSchools.map((s) => [s.slug, s])), [allSchools]);
  // Same tier grouping as /schools and the picker, as <optgroup>s - a flat
  // 27-entry select of mixed elementary/middle/high/preschool is a wall.
  const schoolGroups = useMemo(() => {
    const inScope = districtKey ? new Set(districtKey.split(",")) : null;
    const schools = inScope ? allSchools.filter((s) => s.district_id && inScope.has(s.district_id)) : allSchools;
    return SCHOOL_TYPE_TIERS.map((tier) => ({
      ...tier,
      schools: schools.filter((s) => (s.school_type ?? "other") === tier.key),
    })).filter((g) => g.schools.length > 0);
  }, [allSchools, districtKey]);

  const isFiltered = !!(search || school || category);
  const clearAll = () => {
    setSearch("");
    setQuery("");
    setSchool("");
    setCategory("");
    setOffset(0);
  };

  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);

  return (
    <div>
      <SeoHead
        title={t("{{towns}} schools staff directory · schoolz", { towns: townsLabel(myTowns) })}
        description={t("Search every {{towns}} public school staff member by name, role, or school - teachers, front office, nurses, counselors - with their email and phone number.", { towns: townsLabel(myTowns) })}
        path="/directory"
      />
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>{t("Staff directory")}</h2>
        <Link to="/schools">{t("Browse schools")}</Link>
      </div>

      <div className="search" style={{ marginBottom: 8 }}>
        <IconSearch />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("Search by name, title, or school…")}
          aria-label={t("Search the staff directory")}
          autoComplete="off"
        />
        {search && (
          <button className="search-clear" onClick={() => setSearch("")} aria-label={t("Clear search")}>
            <IconX />
          </button>
        )}
      </div>

      <div className="dir-filters">
        <select
          value={school}
          onChange={(e) => {
            setSchool(e.target.value);
            setOffset(0);
          }}
          aria-label={t("Filter by school")}
        >
          <option value="">{t("All schools")}</option>
          {schoolGroups.map((g) => (
            <optgroup label={g.label} key={g.key}>
              {g.schools.map((s) => (
                <option value={s.slug} key={s.id}>
                  {s.short_name || s.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {isFiltered && (
          <button className="dir-clear" onClick={clearAll}>
            <IconX />
            {t("Clear")}
          </button>
        )}
      </div>

      {/* Counts come from the search result set, before the category
          filter is applied - so a chip always says how many you'd get by
          picking it, and picking one never zeroes out the others. */}
      {(data?.categories.length ?? 0) > 0 && (
        <div className="chips" role="group" aria-label={t("Filter by kind of staff")}>
          <button
            className="chip"
            aria-pressed={category === ""}
            onClick={() => {
              setCategory("");
              setOffset(0);
            }}
          >
            {t("All", { context: "directory" })}
          </button>
          {data!.categories.map((c) => (
            <button
              className="chip"
              aria-pressed={category === c.key}
              key={c.key}
              onClick={() => {
                setCategory(category === c.key ? "" : c.key);
                setOffset(0);
              }}
            >
              {c.label}
              <span className="chip-count">{c.count}</span>
            </button>
          ))}
        </div>
      )}

      {error ? (
        <p className="note">{t("Couldn't load the directory just now. Try again in a moment.")}</p>
      ) : loading && !data ? (
        <div className="dir-list" aria-hidden="true">
          {Array.from({ length: 8 }).map((_, i) => (
            <div className="dir-row skeleton" key={i}>
              <div className="dir-avatar shim" />
              <div style={{ flex: 1 }}>
                <div className="shim line" style={{ width: "40%" }} />
                <div className="shim line" style={{ width: "62%", height: 10 }} />
              </div>
            </div>
          ))}
        </div>
      ) : total === 0 ? (
        <p className="note">
          {query.trim() ? t('Nobody in the directory matches "{{query}}".', { query: query.trim() }) : t("No staff listed yet for this filter.")}
        </p>
      ) : (
        <>
          <div className="dir-count">
            {total === 1 ? t("{{from}}–{{to}} of {{total}} person", { from, to, total }) : t("{{from}}–{{to}} of {{total}} people", { from, to, total })}
          </div>
          <div className={`dir-list ${loading ? "busy" : ""}`}>
            {data!.items.map((m) => {
              const only = m.schools.length === 1 ? m.schools[0] : null;
              // A school logo only stands for someone who works at exactly
              // one school; for anyone else (the district preschool nurse,
              // an itinerant ESL teacher) it would pick one school's crest
              // arbitrarily and imply the wrong thing, so they get initials.
              const logo = only ? schoolsBySlug.get(only.slug)?.logo_url : undefined;
              return (
                <div className="dir-row" key={m.id}>
                  {logo && only ? (
                    <img className={logoClass("dir-avatar", only.slug)} src={logo} alt="" />
                  ) : (
                    <span className="dir-avatar initials" aria-hidden="true">
                      {initials(m.full_name)}
                    </span>
                  )}
                  <div className="dir-main">
                    <div className="dir-name">{m.full_name}</div>
                    {(m.title || m.department) && (
                      <div className="dir-title">{[m.title, m.department].filter(Boolean).join(" · ")}</div>
                    )}
                    {only ? (
                      <Link className="dir-school" to={`/schools/${only.slug}`}>
                        {only.short_name || only.name}
                      </Link>
                    ) : (
                      // Every school named in the tooltip - the label only
                      // has room for a count, but "which three?" is exactly
                      // what someone looking at an itinerant teacher asks.
                      <span
                        className={`dir-school multi ${m.is_district_wide ? "district" : ""}`}
                        title={m.schools.map((s) => s.short_name || s.name).join(", ")}
                      >
                        {m.affiliation}
                      </span>
                    )}
                  </div>
                  <div className="dir-actions">
                    {m.email && (
                      <a
                        className="btn icon dir-mail"
                        href={`mailto:${m.email}`}
                        title={m.email}
                        aria-label={t("Email {{name}}", { name: m.full_name })}
                        onClick={() => trackEvent("action", { action: "directory_email", method: "mailto" })}
                      >
                        <IconMail />
                        {/* Shown only where there's room for it (CSS) - on a
                            phone the icon is the target, but on a laptop the
                            address itself is usually what someone came for,
                            and hiding it behind a hover title makes them
                            click just to read it. */}
                        <span className="dir-email-text">{m.email}</span>
                      </a>
                    )}
                    {m.phone && (
                      <a
                        className="btn icon"
                        href={telHref(m.phone)}
                        title={m.phone}
                        aria-label={t("Call {{name}}", { name: m.full_name })}
                        onClick={() => trackEvent("action", { action: "directory_call", method: "tel" })}
                      >
                        <IconPhone />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {total > PAGE_SIZE && (
            <div className="dir-pager">
              <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                <IconChevronLeft />
                {t("Previous")}
              </button>
              <button className="btn" disabled={to >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
                {t("Next")}
                <IconChevronRight />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
