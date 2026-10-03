import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconSearch } from "../components/icons";
import { logoClass } from "../lib/logos";
import { usePrerenderReady } from "../lib/prerenderReady";
import { useMySchools } from "../lib/mySchools";
import { useAuth } from "../context/AuthContext";
import { SCHOOL_TYPE_TIERS } from "../lib/schoolType";
import { defaultTown, pickerTowns, schoolsInTown, searchSchools } from "../lib/towns";
import { trackEvent } from "../lib/track";
import type { School } from "../types";

/** First-visit school picker. Saves to this device - no account needed.
 * Grouped by town, not district: a Voorhees family's K-8 schools and high
 * school are two different districts, and a family shouldn't need to know
 * that to find both. */
export function PickSchoolsPage() {
  const { t } = useTranslation();
  const { allSchools, districtsById, slugs, setSlugs, fromAccount, loading } = useMySchools();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [picked, setPicked] = useState<string[]>(slugs);
  const [q, setQ] = useState("");
  const [town, setTown] = useState<string | null>(null);

  const towns = useMemo(() => pickerTowns(allSchools, districtsById), [allSchools, districtsById]);

  // A crawler has no picked schools, so /lunch (and anything else needing
  // them) redirects it here - and the redirecting page's own ready flag is
  // cleared as it unmounts. Without this, every prerender of /lunch waited
  // out its full timeout, retried on all three scrapers.
  usePrerenderReady(!loading);

  // `slugs` (account-linked schools especially) loads asynchronously, so
  // seeding `picked` once at mount (before that data arrives) leaves the
  // checkboxes permanently blank even though the account really does have
  // schools tracked. Sync once loading finishes - a one-shot transition,
  // so it never fights the visitor's own clicks afterward. The opening
  // town is chosen at the same moment, from those same picks.
  useEffect(() => {
    if (loading || !towns.length) return;
    setPicked(slugs);
    const bySlug = new Map(allSchools.map((s) => [s.slug, s]));
    setTown((current) => current ?? defaultTown(towns, slugs.map((sl) => bySlug.get(sl)).filter((s): s is School => Boolean(s)), districtsById));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, towns.length]);

  const searching = q.trim().length > 0;
  const visible = useMemo(() => {
    if (searching) return searchSchools(q, allSchools, districtsById);
    return town ? schoolsInTown(town, allSchools, districtsById) : [];
  }, [searching, q, town, allSchools, districtsById]);

  const pickedCountIn = (tw: string) => schoolsInTown(tw, allSchools, districtsById).filter((s) => picked.includes(s.slug)).length;

  // Within a town, name the district only for a school outside the town's
  // own one (Eastern, under Voorhees) - that's the surprise worth a label.
  const homeDistrictId = useMemo(() => {
    if (!town) return null;
    const counts = new Map<string, number>();
    for (const s of schoolsInTown(town, allSchools, districtsById)) {
      if (s.district_id && districtsById.get(s.district_id)?.towns.length === 1) counts.set(s.district_id, (counts.get(s.district_id) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
  }, [town, allSchools, districtsById]);

  const toggle = (s: School) => setPicked((p) => (p.includes(s.slug) ? p.filter((x) => x !== s.slug) : [...p, s.slug]));

  const save = () => {
    setSlugs(picked);
    trackEvent("schools_picked", { count: picked.length });
    navigate("/");
  };

  return (
    <>
      <div className="hero">
        <h1>{t("Choose your schools")}</h1>
        <p>
          {t("Pick one or more. We'll remember them on this device, no account needed. Bookmark the page and you're done.")}
          {fromAccount && ` ${t("Your linked children's schools are already included.")}`}
        </p>
      </div>
      <label className="search">
        <IconSearch />
        <input placeholder={t("Search schools or towns…")} value={q} onChange={(e) => setQ(e.target.value)} />
      </label>

      {towns.length > 1 && !searching && (
        <div className="chips town-chips" role="group" aria-label={t("Town")}>
          {towns.map((tw) => {
            const n = pickedCountIn(tw);
            return (
              <button key={tw} className="chip town-chip" aria-pressed={town === tw} onClick={() => setTown(tw)}>
                {tw}
                {n > 0 && <span className="chip-count">{n}</span>}
              </button>
            );
          })}
        </div>
      )}

      {!searching && !town && <p className="fine">{t("Pick your town to see its schools, or search for one by name.")}</p>}
      {searching && visible.length === 0 && <p className="fine">{t("No schools match “{{q}}”.", { q: q.trim() })}</p>}

      {SCHOOL_TYPE_TIERS.map((tier) => {
        const group = visible.filter((s) => (s.school_type ?? "other") === tier.key);
        if (group.length === 0) return null;
        return (
          <div key={tier.key}>
            <div className="tier">{t(tier.label)}</div>
            <div className="sgrid">
              {group.map((s) => {
                const district = s.district_id ? districtsById.get(s.district_id) : undefined;
                const showDistrict = searching ? towns.length > 1 : Boolean(district && homeDistrictId && s.district_id !== homeDistrictId);
                return (
                  <button className="sopt" aria-pressed={picked.includes(s.slug)} onClick={() => toggle(s)} key={s.id}>
                    <span className="box" />
                    {s.logo_url ? <img className={logoClass("sopt-logo", s.slug)} src={s.logo_url} alt="" /> : null}
                    <span className="sopt-text">
                      {s.short_name || s.name}
                      {showDistrict && district && <small>{searching ? district.towns.join(", ") : district.name}</small>}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}

      <button className="cta" onClick={save} disabled={picked.length === 0}>
        {picked.length === 0 ? t("Pick at least one school") : t("Show me today ({{n}})", { n: picked.length })}
      </button>
      {!user && (
        <p className="fine">
          {t("Want the same list on your phone and laptop, or to link your children?")} <Link to="/login">{t("Sign in")}</Link>. {t("Optional.")}
        </p>
      )}
    </>
  );
}
