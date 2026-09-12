import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { IconSearch } from "../components/icons";
import { useMySchools } from "../lib/mySchools";
import { useAuth } from "../context/AuthContext";
import { SCHOOL_TYPE_TIERS } from "../lib/schoolType";
import { trackEvent } from "../lib/track";
import type { School } from "../types";

/** First-visit school picker. Saves to this device - no account needed. */
export function PickSchoolsPage() {
  const { allSchools, slugs, setSlugs, fromAccount, loading } = useMySchools();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [picked, setPicked] = useState<string[]>(slugs);
  const [q, setQ] = useState("");

  // `slugs` (account-linked schools especially) loads asynchronously, so
  // seeding `picked` once at mount (before that data arrives) leaves the
  // checkboxes permanently blank even though the account really does have
  // schools tracked. Sync once loading finishes - a one-shot transition,
  // so it never fights the visitor's own clicks afterward.
  useEffect(() => {
    if (!loading) setPicked(slugs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return allSchools.filter((s) => !needle || s.name.toLowerCase().includes(needle) || (s.short_name ?? "").toLowerCase().includes(needle));
  }, [allSchools, q]);

  const toggle = (s: School) => setPicked((p) => (p.includes(s.slug) ? p.filter((x) => x !== s.slug) : [...p, s.slug]));

  const save = () => {
    setSlugs(picked);
    trackEvent("schools_picked", { count: picked.length });
    navigate("/");
  };

  return (
    <>
      <div className="hero">
        <h1>Choose your schools</h1>
        <p>
          Pick one or more. We'll remember them on this device, no account needed. Bookmark the page and you're done.
          {fromAccount && " Your linked children's schools are already included."}
        </p>
      </div>
      <label className="search">
        <IconSearch />
        <input placeholder={`Search ${allSchools.length} Cherry Hill schools…`} value={q} onChange={(e) => setQ(e.target.value)} />
      </label>

      {SCHOOL_TYPE_TIERS.map((t) => {
        const group = visible.filter((s) => (s.school_type ?? "other") === t.key);
        if (group.length === 0) return null;
        return (
          <div key={t.key}>
            <div className="tier">{t.label}</div>
            <div className="sgrid">
              {group.map((s) => (
                <button className="sopt" aria-pressed={picked.includes(s.slug)} onClick={() => toggle(s)} key={s.id}>
                  <span className="box" />
                  {s.logo_url ? <img className="sopt-logo" src={s.logo_url} alt="" /> : null}
                  {s.short_name || s.name}
                </button>
              ))}
            </div>
          </div>
        );
      })}

      <button className="cta" onClick={save} disabled={picked.length === 0}>
        {picked.length === 0 ? "Pick at least one school" : `Show me today (${picked.length})`}
      </button>
      {!user && (
        <p className="fine">
          Want the same list on your phone and laptop, or to link your children? <Link to="/login">Sign in</Link>. Optional.
        </p>
      )}
    </>
  );
}
