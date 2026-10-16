import { useSyncExternalStore } from "react";

/** Where a Localz visitor is, as far as they've told us: a county, and the
 * point it came from when there is one. Kept on this device only.
 *
 * Everything that turns a ZIP or the phone's position into a county happens
 * here, against a table of every New Jersey ZIP shipped with the app
 * (lib/njZips.json, scripts/build_nj_zips.py). Nothing about where someone
 * is reaches our server or anyone else: the server only ever hears the
 * county name, as a search filter. */

export type LocalzWhere = {
  county: string;
  /** How it was set, for the button: "ZIP 07075", "Area code 201", ... */
  how: "zip" | "area" | "gps" | "county";
  zip?: string;
  areaCode?: string;
  /** Rounded to 2 decimals (~half a mile) before it's ever stored. */
  lat?: number;
  lon?: number;
};

const KEY = "localz_where";
const OLD_COUNTY_KEY = "localz_county";
const CHANGE_EVENT = "localz-where-change";

/** NJ area codes and the counties they mostly cover. An area code is where
 * a number was issued, not where its owner is, so it only narrows the
 * choice - the visitor picks the county. */
export const AREA_CODES: Record<string, string[]> = {
  "201": ["Bergen", "Hudson"],
  "551": ["Bergen", "Hudson"],
  "973": ["Essex", "Passaic", "Morris", "Sussex"],
  "862": ["Essex", "Passaic", "Morris", "Sussex"],
  "908": ["Union", "Somerset", "Hunterdon", "Warren", "Morris", "Middlesex"],
  "732": ["Middlesex", "Monmouth", "Ocean", "Somerset", "Union"],
  "848": ["Middlesex", "Monmouth", "Ocean", "Somerset", "Union"],
  "609": ["Mercer", "Burlington", "Atlantic", "Cape May", "Ocean", "Cumberland"],
  "640": ["Mercer", "Burlington", "Atlantic", "Cape May", "Ocean", "Cumberland"],
  "856": ["Camden", "Gloucester", "Burlington", "Salem", "Cumberland", "Atlantic"],
};

export function countiesForAreaCode(code: string): string[] | null {
  return AREA_CODES[code.trim()] ?? null;
}

type ZipTable = Record<string, [string, number, number]>;
let zipTable: Promise<ZipTable> | null = null;

/** ~20 KB, so it's only fetched when someone sets a location. */
function loadZipTable(): Promise<ZipTable> {
  zipTable ??= import("./njZips.json").then((m) => m.default as unknown as ZipTable);
  return zipTable;
}

export async function whereForZip(zip: string): Promise<LocalzWhere | null> {
  const clean = zip.trim();
  if (!/^\d{5}$/.test(clean)) return null;
  const row = (await loadZipTable())[clean];
  if (!row) return null;
  return { county: row[0], how: "zip", zip: clean, lat: row[1], lon: row[2] };
}

function km(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = Math.PI / 180;
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

/** Farther than this from every NJ ZIP's center is outside New Jersey. */
const MAX_KM = 25;

/** The county of the nearest NJ ZIP to a point, or null outside NJ. */
export async function whereForPoint(lat: number, lon: number): Promise<LocalzWhere | null> {
  const table = await loadZipTable();
  let best: { zip: string; county: string; d: number } | null = null;
  for (const [zip, [county, zlat, zlon]] of Object.entries(table)) {
    const d = km(lat, lon, zlat, zlon);
    if (!best || d < best.d) best = { zip, county, d };
  }
  if (!best || best.d > MAX_KM) return null;
  return { county: best.county, how: "gps", lat: Math.round(lat * 100) / 100, lon: Math.round(lon * 100) / 100 };
}

let cachedRaw: string | null | undefined;
let cachedValue: LocalzWhere | null = null;

function read(): LocalzWhere | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(KEY);
    if (raw === null) {
      // Before "Set my location", only a county was remembered.
      const county = localStorage.getItem(OLD_COUNTY_KEY);
      if (county) raw = JSON.stringify({ county, how: "county" });
    }
  } catch {
    return cachedValue; // storage blocked: whatever was set this page load
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      const parsed = raw ? JSON.parse(raw) : null;
      cachedValue = parsed && typeof parsed.county === "string" ? (parsed as LocalzWhere) : null;
    } catch {
      cachedValue = null;
    }
  }
  return cachedValue;
}

export function saveWhere(where: LocalzWhere | null): void {
  try {
    localStorage.removeItem(OLD_COUNTY_KEY);
    if (where) localStorage.setItem(KEY, JSON.stringify(where));
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: kept for this page only */
    cachedRaw = where ? JSON.stringify(where) : null;
    cachedValue = where;
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

/** The saved location, shared by every Localz page and kept in step. */
export function useLocalzWhere(): LocalzWhere | null {
  return useSyncExternalStore(subscribe, read, () => null);
}
