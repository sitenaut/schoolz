import { apiFetch } from "../api";
import { type Criteria, forgetDevice } from "./localzFit";
import type { Box } from "./localzWhere";
import { ROUTER_BASENAME } from "./i18n";

/** Localz: community resources (food, housing, health, ...) for families who
 * need help. Design: docs/LOCALZ_DESIGN.md. Rules that shape this code:
 *
 * - Nothing about what a visitor searches for goes in a URL. Search text is
 *   POSTed and kept in component state, so it never reaches access logs,
 *   RUM, browser history or a shared link. Category pages have URLs; typed
 *   text doesn't.
 * - No GA on Localz pages (lib/analytics.ts and AppShell check isLocalzPath).
 * - Labels are neutral ("Help with bills"), never "emergency assistance for
 *   the needy". */

export type ResourceSummary = {
  id: string;
  name: string;
  organization_name: string | null;
  location_name: string | null;
  description: string | null;
  phone: string | null;
  address: string | null;
  city: string | null;
  hours_text: string | null;
  categories: string[];
  complete: boolean;
  /** Serves all of New Jersey (its own service area, or NJ 211 lists it
   * for most counties). */
  statewide: boolean;
  last_assured_on: string | null;
  /** Who it's for, structured from its eligibility sentence; null until
   * that's been read. Matched on the device (lib/localzFit.ts). */
  eligibility: Criteria | null;
  /** A provider's "Closed today" or temporary closure, while it lasts. */
  closure?: { starts_on: string; ends_on: string; note: string | null } | null;
  /** A confidential location (a shelter): no address is ever sent. */
  location_confidential?: boolean;
  /** Miles from the visitor's point, measured on the device (closest first). */
  distance_miles?: number;
  /** The next days it meets, for a monthly, every-other-week or seasonal schedule. */
  next_open?: { on: string; times: string }[];
  /** "online" or "both" (in person or online), when a provider said. */
  delivery?: "in_person" | "online" | "both" | null;
  /** How a program takes people; `opens_on` only for a closed one. */
  signup?: { status: "drop_in" | "open" | "waitlist" | "closed"; opens_on: string | null; how: string | null } | null;
};

export type ResourceDetail = ResourceSummary & {
  email: string | null;
  website: string | null;
  postal_code: string | null;
  latitude: number | null;
  longitude: number | null;
  eligibility_text: string | null;
  application_process: string | null;
  fees: string | null;
  required_documents: string[];
  languages: string[];
  accessibility: string | null;
  transportation: string | null;
  service_areas: string[];
  taxonomy_names: string[];
  alert: string | null;
  /** "This week only" hours a provider posted, for the current week. */
  week_hours_text?: string | null;
  /** Dates the provider posted, soonest first. */
  upcoming_dates?: { id: string; title: string; start_time: string; end_time: string | null; venue_name: string | null; venue_address: string | null; note: string | null }[];
  /** Volunteer roles, items to donate, a wish-list link. */
  ways_to_help?: { volunteer_roles: string[]; volunteer_how: string | null; donations: string[]; wishlist_url: string | null } | null;
  missing_core: string[];
  source: string;
  source_url: string | null;
  updated_at: string;
};

export type ResourceCategoryCount = { key: string; label: string; count: number };

/** A kind of service within a category ("Food Pantries"), from NJ 211's
 * taxonomy; `code` is what the search filters on. */
export type ResourceType = { code: string; name: string; count: number };

export type ResourceSearch = {
  category?: string;
  query?: string;
  county?: string;
  type?: string;
  /** Any of these taxonomy codes (Neighborz's "other help"). */
  types?: string[];
  /** Only what a closest-first list couldn't place inside this box. */
  outside?: Box;
  page?: number;
  offset?: number;
  page_size?: number;
};

/** [id, lat, lon, statewide] for every match placed inside a box. */
export type NearbyPoint = [string, number, number, boolean];

export type LocalzCategory = {
  key: string;
  /** Page heading and tile label. */
  label: string;
  /** Bottom-tab label: one short word, so seven tabs fit a phone. */
  navLabel: string;
  /** Tile line - what it helps with, in plain words. */
  blurb: string;
  /** Shown in the main nav; the rest are reached from the Localz home. */
  inNav: boolean;
};

// Keys match backend/resources/categories.py. Labels pass through t().
export const LOCALZ_CATEGORIES: LocalzCategory[] = [
  { key: "food", label: "Food", navLabel: "Food", blurb: "Pantries, meals and help with groceries", inNav: true },
  { key: "english", label: "Learn English", navLabel: "English", blurb: "English classes and reading help", inNav: true },
  { key: "housing-bills", label: "Housing & Bills", navLabel: "Housing", blurb: "Rent, utilities and a place to stay", inNav: true },
  { key: "health", label: "Health", navLabel: "Health", blurb: "Clinics, coverage, counseling and recovery", inNav: true },
  { key: "kids-family", label: "Kids & Family", navLabel: "Family", blurb: "Child care, early learning and parenting", inNav: true },
  { key: "money-work", label: "Money & Work", navLabel: "Money", blurb: "Benefits, jobs, taxes and classes", inNav: true },
  { key: "legal-safety", label: "Legal & Safety", navLabel: "Legal", blurb: "Legal aid and staying safe", inNav: false },
  { key: "everyday-needs", label: "Everyday Needs", navLabel: "Everyday", blurb: "Clothing, diapers, rides and holiday help", inNav: false },
];

export const categoryByKey = (key: string | undefined) => LOCALZ_CATEGORIES.find((c) => c.key === key);

/** Every New Jersey county - the crawl asks NJ 211 about each one. */
export const LOCALZ_COUNTIES = [
  "Atlantic", "Bergen", "Burlington", "Camden", "Cape May", "Cumberland", "Essex", "Gloucester", "Hudson", "Hunterdon", "Mercer",
  "Middlesex", "Monmouth", "Morris", "Ocean", "Passaic", "Salem", "Somerset", "Sussex", "Union", "Warren",
];

export type HelpLine = { label: string; number: string; tel?: string; sms?: string; body?: string };

/** Always on screen in Localz. Calls go to public statewide lines; the text
 * line is the National Domestic Violence Hotline's, for someone who can't
 * safely be overheard on a call. */
export const HELP_NOW: HelpLine[] = [
  { label: "Any kind of help", number: "211", tel: "211" },
  { label: "Crisis or suicide", number: "988", tel: "988" },
  { label: "Domestic violence", number: "1-800-572-7233", tel: "18005727233" },
  { label: "Domestic violence: text BEGIN", number: "88788", sms: "88788", body: "BEGIN" },
  { label: "Child abuse", number: "1-877-652-2873", tel: "18776522873" },
];

/** The link for a line: a call, or a text with its keyword filled in.
 * `sms:N?&body=` is the form both iPhone and Android read. */
export function helpLineHref(line: HelpLine): string {
  if (line.sms) return `sms:${line.sms}${line.body ? `?&body=${encodeURIComponent(line.body)}` : ""}`;
  return `tel:${line.tel}`;
}

/** Quick exit lands on the schoolz Today page - school days, lunch and
 * weather, nothing about getting help. Deliberately not another website:
 * phones hand outside links to apps (iPhone Chrome opened google.com in the
 * Google app; weather.com opens The Weather Channel app) and an installed
 * web app or a desktop browser can open them in a new tab, and in every one
 * of those cases the Localz tab stayed open behind it. A page on this site
 * always opens in this same tab. */
export const QUICK_EXIT_PATH = "/";

/** Leave Localz at once: empty the screen, then reload this tab as the
 * Today page, replacing the current history entry (a full reload also
 * drops anything typed into a search or the chat). Earlier Localz pages
 * stay in Back history - a browser won't let a site erase those. */
export function quickExit(): void {
  try {
    sessionStorage.clear();
  } catch {
    /* private mode */
  }
  // "Remember on this device" too: someone who has to leave in a hurry is
  // better served by losing their answers than by leaving them behind.
  forgetDevice();
  document.title = "schoolz";
  document.body.replaceChildren();
  window.location.replace(`${ROUTER_BASENAME}${QUICK_EXIT_PATH}`);
}

export { isLocalzPath } from "./localzPath";

export async function searchResources(body: ResourceSearch): Promise<{ items: ResourceSummary[]; total: number }> {
  const r = await apiFetch("/resources/search", { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`search failed: ${r.status}`);
  return r.json();
}

/** Every match with a place inside a coarse box, for the device to
 * measure - the visitor's own point is never sent. */
export async function fetchNearby(body: { category?: string; query?: string; type?: string; box: Box }): Promise<NearbyPoint[]> {
  const r = await apiFetch("/resources/nearby", { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`nearby failed: ${r.status}`);
  return (await r.json()).points;
}

export async function fetchResourcesByIds(ids: string[]): Promise<ResourceSummary[]> {
  if (ids.length === 0) return [];
  const r = await apiFetch("/resources/by-ids", { method: "POST", body: JSON.stringify({ ids }) });
  if (!r.ok) throw new Error(`by-ids failed: ${r.status}`);
  return r.json();
}

/** Kinds of service in a category, counted for the same county and text
 * as the list (not the chosen type, so the others never read zero). */
export async function fetchResourceTypes(body: ResourceSearch): Promise<ResourceType[]> {
  const r = await apiFetch("/resources/types", { method: "POST", body: JSON.stringify({ ...body, type: undefined, page: undefined, page_size: undefined }) });
  return r.ok ? r.json() : [];
}

export async function fetchResource(id: string): Promise<ResourceDetail | null> {
  const r = await apiFetch(`/resources/${encodeURIComponent(id)}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`resource failed: ${r.status}`);
  return r.json();
}

export async function fetchResourceCategories(county?: string): Promise<ResourceCategoryCount[]> {
  const r = await apiFetch(`/resources/categories${county ? `?county=${encodeURIComponent(county)}` : ""}`);
  return r.ok ? r.json() : [];
}

/** "Last confirmed March 2026" - month precision is enough and reads
 * naturally; a date string from the API is a plain YYYY-MM-DD. */
export function confirmedLabel(isoDate: string | null, locale: string): string | null {
  if (!isoDate) return null;
  const [y, m] = isoDate.split("-").map(Number);
  if (!y || !m) return null;
  return new Date(y, m - 1, 1).toLocaleDateString(locale, { month: "long", year: "numeric" });
}

/** NJ 211 writes "None" for no fee. */
export function isFree(fees: string | null): boolean {
  return !!fees && /^\s*(none|free|no fees?|no cost)\b/i.test(fees);
}

export function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}

export function mapsHref(r: Pick<ResourceDetail, "address" | "city" | "postal_code">): string | null {
  const text = [r.address, r.city, r.postal_code].filter(Boolean).join(", ");
  return text ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(text)}` : null;
}
