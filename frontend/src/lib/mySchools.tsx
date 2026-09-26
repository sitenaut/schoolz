import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import type { DistrictSummary, School } from "../types";
import { pickerTowns, townsForSchool } from "./towns";

/**
 * "My schools" without an account: the picker saves slugs on this device
 * (localStorage - not sessionStorage, deliberately: it survives closing
 * the browser/tab, which a session cookie wouldn't, and needs no login)
 * so the Today feed works for an anonymous parent who just bookmarked the
 * site. A logged-in guardian with linked kids gets their kids' schools
 * from the server instead, which also syncs across devices.
 *
 * Separately, which of "my schools" are currently shown (the top-ribbon
 * filter) is its own persisted list - inactiveSlugs, empty by default so
 * everything shows until the visitor hides something. Tracking the
 * hidden set (not the shown set) means a newly-added school is visible
 * automatically without any extra bookkeeping when the picker list changes.
 */
const KEY = "schoolz_my_schools";
const INACTIVE_KEY = "schoolz_inactive_schools";
// Default OFF: district items (Board of Ed meetings, etc.) show
// everywhere dated items show up (Calendar's list, Today's upcoming
// dates) - not just Calendar - unless a visitor discovers and enables
// the "exclude district" checkbox themselves; status items (closed/half
// day/delayed) and grading dates always show regardless either way (see
// lib/districtItems.ts:isNoisyDistrictItem). The Calendar page is the
// only place with a control to turn it on.
// _v2: the default flipped from on to off, and browsers that saved a value
// under the old default kept it; a new key starts everyone at the new default.
/** Fired when someone taps a school-ribbon chip - pages that narrow to one
 * school from a link (Calendar's ?school=) hand control back to the ribbon. */
export const RIBBON_CHANGE_EVENT = "schoolz:ribbon-change";

const EXCLUDE_DISTRICT_KEY = "schoolz_exclude_district_v2";

function readBool(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === "1";
  } catch {
    return fallback;
  }
}

function writeBool(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* private mode etc - just won't persist */
  }
}
const PALETTE = ["var(--sch-1)", "var(--sch-2)", "var(--sch-3)", "var(--sch-4)", "var(--sch-5)", "var(--sch-6)"];

function readList(key: string): string[] {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeList(key: string, values: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(values));
  } catch {
    /* private mode etc - just won't persist */
  }
}

type Ctx = {
  /** Every tracked school, for the picker. */
  allSchools: School[];
  districtsById: Map<string, DistrictSummary>;
  /** Towns of the picked schools (falls back to every tracked town) - for
   * copy that used to say "Cherry Hill" unconditionally. */
  myTowns: string[];
  /** The schools the visitor has picked (or their account's), in order. */
  mySchools: School[];
  /** mySchools minus whatever's currently hidden via the ribbon filter. */
  activeSchools: School[];
  slugs: string[];
  setSlugs: (slugs: string[]) => void;
  /** True while we don't yet know whether the visitor has picked anything. */
  loading: boolean;
  /** True when the list came from the guardian's linked kids, not the device. */
  fromAccount: boolean;
  colorFor: (schoolId: string) => string;
  isActive: (schoolId: string) => boolean;
  toggleActive: (school: School) => void;
  activateAll: () => void;
  /** True when the ribbon is currently narrowing the view to a subset. */
  isFiltered: boolean;
  /** Hide generic district items (board meetings, etc.) - see
   * lib/districtItems.ts. Shared/persisted so Calendar's control also
   * governs what Today's dated lists show. */
  excludeDistrict: boolean;
  setExcludeDistrict: (value: boolean) => void;
};

const MySchoolsContext = createContext<Ctx | null>(null);

export function MySchoolsProvider({ children }: { children: React.ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [allSchools, setAllSchools] = useState<School[]>([]);
  const [loadedAll, setLoadedAll] = useState(false);
  const [districts, setDistricts] = useState<DistrictSummary[]>([]);
  const [localSlugs, setLocalSlugs] = useState<string[]>(readList(KEY));
  const [accountSchools, setAccountSchools] = useState<School[] | null>(null);
  // Separate from authLoading/loadedAll - fetching this guardian's linked
  // schools is a third async step that finishes after both of those (it
  // only starts once `user` is known). Without tracking it, `loading`
  // could flip false before this arrives, letting the picker seed itself
  // from an incomplete `slugs` and permanently miss the account's schools.
  const [accountLoaded, setAccountLoaded] = useState(false);
  const [inactiveSlugs, setInactiveSlugs] = useState<string[]>(readList(INACTIVE_KEY));
  const [excludeDistrict, setExcludeDistrictState] = useState<boolean>(readBool(EXCLUDE_DISTRICT_KEY, false));

  const setExcludeDistrict = useCallback((value: boolean) => {
    setExcludeDistrictState(value);
    writeBool(EXCLUDE_DISTRICT_KEY, value);
  }, []);

  useEffect(() => {
    apiFetch("/districts/summary")
      .then((r) => (r.ok ? r.json() : []))
      .then(setDistricts)
      .catch(() => setDistricts([]));
  }, []);
  const districtsById = useMemo(() => new Map(districts.map((d) => [d.id, d])), [districts]);

  useEffect(() => {
    apiFetch("/schools")
      .then((r) => (r.ok ? r.json() : []))
      .then((s: School[]) => {
        setAllSchools(s);
        setLoadedAll(true);
      });
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      setAccountSchools(null);
      setAccountLoaded(true);
      return;
    }
    setAccountLoaded(false);
    apiFetch("/schools/mine")
      .then((r) => (r.ok ? r.json() : []))
      .then((s: School[]) => setAccountSchools(s.length ? s : null))
      .finally(() => setAccountLoaded(true));
  }, [user, authLoading]);

  const setSlugs = useCallback((slugs: string[]) => {
    setLocalSlugs(slugs);
    writeList(KEY, slugs);
  }, []);

  // Your account's linked-kid schools are additive, not a replacement -
  // signing in should never make the picker's own choices disappear
  // (confirmed real bug: a guardian with a child already linked picked
  // different schools at /start and "Show me today" appeared to do
  // nothing, because accountSchools used to win outright). Account
  // schools come first since they're the reason to have an account at
  // all; anything picked locally that isn't already covered follows.
  const mySchools = useMemo(() => {
    const bySlug = new Map(allSchools.map((s) => [s.slug, s]));
    const picked = localSlugs.map((slug) => bySlug.get(slug)).filter((s): s is School => Boolean(s));
    if (!accountSchools) return picked;
    const seen = new Set(accountSchools.map((s) => s.id));
    return [...accountSchools, ...picked.filter((s) => !seen.has(s.id))];
  }, [accountSchools, allSchools, localSlugs]);

  const activeSchools = useMemo(() => {
    const shown = mySchools.filter((s) => !inactiveSlugs.includes(s.slug));
    // Toggling off every school would leave a blank Today/Lunch view with
    // no way back except the "All" chip - show everything instead so the
    // filter can only ever narrow, never empty out, the feed.
    return shown.length > 0 ? shown : mySchools;
  }, [mySchools, inactiveSlugs]);

  const isActive = useCallback((schoolId: string) => activeSchools.some((s) => s.id === schoolId), [activeSchools]);

  const toggleActive = useCallback((school: School) => {
    setInactiveSlugs((prev) => {
      const next = prev.includes(school.slug) ? prev.filter((x) => x !== school.slug) : [...prev, school.slug];
      writeList(INACTIVE_KEY, next);
      return next;
    });
  }, []);

  const activateAll = useCallback(() => {
    setInactiveSlugs([]);
    writeList(INACTIVE_KEY, []);
  }, []);

  const colorFor = useCallback(
    (schoolId: string) => {
      const idx = mySchools.findIndex((s) => s.id === schoolId);
      return PALETTE[(idx >= 0 ? idx : 0) % PALETTE.length];
    },
    [mySchools],
  );

  const myTowns = useMemo(() => {
    const source = mySchools.length ? mySchools : allSchools;
    // Only towns with their own schools here - Eastern also serves Berlin,
    // but a Voorhees family's header shouldn't read "Voorhees & Berlin".
    const known = new Set(pickerTowns(allSchools, districtsById));
    const counts = new Map<string, number>();
    for (const sc of source) {
      for (const t of townsForSchool(sc, districtsById)) if (known.has(t)) counts.set(t, (counts.get(t) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([t]) => t);
  }, [mySchools, allSchools, districtsById]);

  const value: Ctx = {
    allSchools,
    districtsById,
    myTowns,
    mySchools,
    activeSchools,
    // What the picker should show as already checked - the union too,
    // so a guardian's linked-kid schools show as checked without
    // hiding whatever they'd separately picked on this device.
    slugs: mySchools.map((s) => s.slug),
    setSlugs,
    loading: authLoading || !loadedAll || !accountLoaded,
    fromAccount: Boolean(accountSchools),
    colorFor,
    isActive,
    toggleActive,
    activateAll,
    isFiltered: activeSchools.length < mySchools.length,
    excludeDistrict,
    setExcludeDistrict,
  };
  return <MySchoolsContext.Provider value={value}>{children}</MySchoolsContext.Provider>;
}

export function useMySchools(): Ctx {
  const ctx = useContext(MySchoolsContext);
  if (!ctx) throw new Error("useMySchools must be used inside MySchoolsProvider");
  return ctx;
}
