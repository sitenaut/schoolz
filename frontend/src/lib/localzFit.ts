import { useSyncExternalStore } from "react";

/** "What am I eligible for?" - the visitor's answers, and matching them
 * against each listing's criteria, all on this device. The answers never
 * leave it: the server sends every listing's criteria
 * (backend/resources/eligibility.py, the same vocabulary as here) and this
 * file decides which fit.
 *
 * Kept for the visit only (sessionStorage, which Quick exit clears) unless
 * the visitor ticks "Remember on this device".
 *
 * Deliberately never says "not eligible": the answers are rough and the
 * criteria are read from free text, so a listing that doesn't seem to fit
 * is sorted lower and says who it's for, not hidden or marked red. */

export const AGE_BANDS = ["u1", "1-4", "5-12", "13-17", "18-59", "60+"] as const;
export type AgeBand = (typeof AGE_BANDS)[number];
const BAND_RANGE: Record<AgeBand, [number, number]> = {
  u1: [0, 0],
  "1-4": [1, 4],
  "5-12": [5, 12],
  "13-17": [13, 17],
  "18-59": [18, 59],
  "60+": [60, 120],
};
const CHILD_BANDS: AgeBand[] = ["u1", "1-4", "5-12", "13-17"];

/** Asked in the sheet, so an unticked one is a real "no". */
export const FIT_NEEDS = ["veteran_military", "disability", "pregnant_or_new_baby", "uninsured", "job_loss"] as const;
export type FitNeed = (typeof FIT_NEEDS)[number];
/** Who a service is for. Only ever matched (never failed): we don't ask
 * anyone's gender or identity, so not choosing one says nothing. */
export const FIT_FOCUS = ["women", "men", "lgbtq", "survivors"] as const;
export type FitFocus = (typeof FIT_FOCUS)[number];

export type FitAnswers = {
  ages: AgeBand[];
  has: FitNeed[];
  focus: FitFocus[];
  /** Show programs that don't ask about immigration status first. */
  noStatusFirst: boolean;
};

export type Criteria = {
  open_to_all: boolean;
  vague: boolean;
  age_min: number | null;
  age_max: number | null;
  child_age_min: number | null;
  child_age_max: number | null;
  requires: string[];
  focus: string[];
  either: boolean;
  asks_immigration_status: boolean;
  other: string | null;
};

/** yes: everything it asks is something you said. open: open to anyone.
 * check: some of it we can't tell (income, a referral). no: something it
 * asks doesn't match what you said. */
export type FitLevel = "yes" | "open" | "check" | "no";

/** An English label for t(), with its values. */
export type FitLabel = { text: string; vars?: Record<string, string | number> };

export type Fit = {
  level: FitLevel;
  /** What the listing asks, in plain words ("Ages 60 and up"). */
  asks: FitLabel[];
  /** It asks about immigration status, and the visitor wanted those last. */
  asksStatus: boolean;
};

const REQUIRE_LABELS: Record<string, string> = {
  veteran_military: "Veterans and military families",
  disability: "People with disabilities",
  pregnant_or_new_baby: "Pregnancy or a new baby",
  uninsured: "No health insurance",
  job_loss: "Lost a job or hours",
  families_with_children: "Families with children",
  low_income: "Income limits",
  homeless: "Without a stable place to live",
};
const FOCUS_LABELS: Record<string, string> = {
  women: "Focus: women",
  men: "Focus: men",
  lgbtq: "Focus: LGBTQ+",
  survivors: "Focus: survivors of violence",
};

export function hasAnswers(a: FitAnswers | null): a is FitAnswers {
  return !!a && (a.ages.length > 0 || a.has.length > 0 || a.focus.length > 0 || a.noStatusFirst);
}

function ageLabel(min: number | null, max: number | null): FitLabel {
  if (min !== null && max !== null) return { text: "Ages {{min}}–{{max}}", vars: { min, max } };
  if (min !== null) return { text: "Ages {{min}} and up", vars: { min } };
  return { text: "Ages {{max}} and under", vars: { max: max as number } };
}

function childLabel(min: number | null, max: number | null): FitLabel {
  if (min !== null && max !== null) return { text: "Families with children {{min}}–{{max}}", vars: { min, max } };
  if (min !== null) return { text: "Families with children {{min}} and older", vars: { min } };
  return { text: "Families with children {{max}} and under", vars: { max: max as number } };
}

/** Who a listing is for, in plain words - for its details page whether or
 * not the visitor has answered anything. */
export function describe(c: Criteria): FitLabel[] {
  const out: FitLabel[] = [];
  if (c.age_min !== null || c.age_max !== null) out.push(ageLabel(c.age_min, c.age_max));
  if (c.child_age_min !== null || c.child_age_max !== null) out.push(childLabel(c.child_age_min, c.child_age_max));
  for (const r of c.requires) if (REQUIRE_LABELS[r]) out.push({ text: REQUIRE_LABELS[r] });
  for (const f of c.focus) if (FOCUS_LABELS[f]) out.push({ text: FOCUS_LABELS[f] });
  if (c.other) out.push({ text: c.other });
  return out;
}

type Outcome = "met" | "failed" | "unknown";

function overlaps(bands: AgeBand[], min: number | null, max: number | null): boolean {
  const lo = min ?? 0;
  const hi = max ?? 120;
  return bands.some((b) => BAND_RANGE[b][0] <= hi && BAND_RANGE[b][1] >= lo);
}

/** Match one listing. null: its criteria haven't been read yet, or there's
 * nothing to match against. */
export function fitFor(c: Criteria | null | undefined, a: FitAnswers | null): Fit | null {
  if (!c || !hasAnswers(a)) return null;
  const asksStatus = a.noStatusFirst && c.asks_immigration_status;
  const children = a.ages.filter((b) => CHILD_BANDS.includes(b));
  // Conditions "either" can choose between, and ones that always apply
  // (income and anything unusual hold whichever group you're in).
  // Age is kept apart from the rest: with "either", being the right age
  // alone is too weak to call a listing yours ("adults with disabilities"
  // read as "adults, or people with disabilities" called it a fit for any
  // adult), so it can lift a listing only to "check".
  const ages: Outcome[] = [];
  const group: Outcome[] = [];
  const always: Outcome[] = [];

  if (c.age_min !== null || c.age_max !== null) {
    ages.push(a.ages.length === 0 ? "unknown" : overlaps(a.ages, c.age_min, c.age_max) ? "met" : "failed");
  }
  if (c.child_age_min !== null || c.child_age_max !== null) {
    ages.push(a.ages.length === 0 ? "unknown" : overlaps(children, c.child_age_min, c.child_age_max) ? "met" : "failed");
  }
  for (const r of c.requires) {
    if ((FIT_NEEDS as readonly string[]).includes(r)) group.push(a.has.includes(r as FitNeed) ? "met" : "failed");
    else if (r === "families_with_children") group.push(a.ages.length === 0 ? "unknown" : children.length ? "met" : "failed");
    else if (r === "homeless") group.push("unknown");
    else always.push("unknown"); // low_income: not asked
  }
  if (c.focus.length) group.push(c.focus.some((f) => a.focus.includes(f as FitFocus)) ? "met" : "unknown");
  if (c.other || c.vague) always.push("unknown");

  let groupOutcome: Outcome | null = null;
  if (c.either && group.length) {
    const any = [...ages, ...group];
    groupOutcome = group.includes("met") ? "met" : any.every((o) => o === "failed") ? "failed" : "unknown";
  } else {
    const any = [...ages, ...group];
    if (any.length) groupOutcome = any.includes("failed") ? "failed" : any.every((o) => o === "met") ? "met" : "unknown";
  }
  const all = [...(groupOutcome ? [groupOutcome] : []), ...always];
  let level: FitLevel;
  if (all.includes("failed")) level = "no";
  else if (all.length === 0) level = c.open_to_all ? "open" : "check";
  else level = all.every((o) => o === "met") ? "yes" : "check";
  return { level, asks: describe(c), asksStatus };
}

const ORDER: Record<FitLevel, number> = { yes: 0, open: 1, check: 2, no: 4 };

/** Best fits first, then open-to-all, then the ones to check, then the
 * rest; the server's order otherwise. A listing whose criteria aren't read
 * yet sits with "check"; one that asks about immigration status, when the
 * visitor asked for those last, drops below the others of its level. */
export function sortByFit<T extends { eligibility?: Criteria | null }>(items: T[], a: FitAnswers | null): T[] {
  if (!hasAnswers(a)) return items;
  const rank = (item: T) => {
    const fit = fitFor(item.eligibility, a);
    return (fit ? ORDER[fit.level] : 3) + (fit?.asksStatus ? 0.5 : 0);
  };
  return items
    .map((item, i) => ({ item, i, r: rank(item) }))
    .sort((x, y) => x.r - y.r || x.i - y.i)
    .map((x) => x.item);
}

// ---- storage ------------------------------------------------------------------

const KEY = "localz_fit";
const CHANGE_EVENT = "localz-fit-change";

let cachedRaw: string | null | undefined;
let cachedValue: { answers: FitAnswers; remember: boolean } | null = null;
let memoryOnly: { answers: FitAnswers; remember: boolean } | null = null;

function clean(raw: unknown): FitAnswers | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const pick = <T extends string>(v: unknown, allowed: readonly T[]): T[] =>
    Array.isArray(v) ? (v.filter((x) => (allowed as readonly unknown[]).includes(x)) as T[]) : [];
  return { ages: pick(r.ages, AGE_BANDS), has: pick(r.has, FIT_NEEDS), focus: pick(r.focus, FIT_FOCUS), noStatusFirst: r.noStatusFirst === true };
}

function read(): { answers: FitAnswers; remember: boolean } | null {
  let raw: string | null;
  let remember = false;
  try {
    raw = sessionStorage.getItem(KEY);
    if (raw === null) {
      raw = localStorage.getItem(KEY);
      remember = raw !== null;
    }
  } catch {
    return memoryOnly; // storage blocked: kept for this page load
  }
  const tagged = raw === null ? null : `${remember ? "L" : "S"}${raw}`;
  if (tagged !== cachedRaw) {
    cachedRaw = tagged;
    try {
      const answers = raw ? clean(JSON.parse(raw)) : null;
      cachedValue = answers ? { answers, remember } : null;
    } catch {
      cachedValue = null;
    }
  }
  return cachedValue;
}

/** Save the answers for this visit, or on this device when `remember`;
 * null forgets them everywhere. */
export function saveFit(answers: FitAnswers | null, remember = false): void {
  const value = answers && hasAnswers(answers) ? JSON.stringify(answers) : null;
  try {
    sessionStorage.removeItem(KEY);
    localStorage.removeItem(KEY);
    if (value) (remember ? localStorage : sessionStorage).setItem(KEY, value);
  } catch {
    memoryOnly = value && answers ? { answers, remember } : null;
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function useLocalzFit(): { answers: FitAnswers; remember: boolean } | null {
  return useSyncExternalStore(subscribe, read, () => null);
}
