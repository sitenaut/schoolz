import { useEffect, useState } from "react";
import { apiFetch } from "../api";

/** A link to someone else's seasonal guide (GET /seasonal-guides). We hold
 * the link and our own one-line note, never the guide's listings - see
 * backend models.SeasonalGuide. */
export type SeasonalGuide = {
  id: string;
  season: string;
  title: string;
  publisher: string;
  url: string;
  note: string | null;
  starts_on: string;
  ends_on: string;
  sort_order: number;
};

export type Season = { season: string; emoji: string; heading: string; guides: SeasonalGuide[] };

// A season with no entry here still works, with a generic look. "fall" is
// November (Halloween's season covers September and October), so its badge
// is the turkey.
const SEASON_LOOK: Record<string, { emoji: string; heading: string }> = {
  halloween: { emoji: "🎃", heading: "Halloween & fall" },
  fall: { emoji: "🦃", heading: "Thanksgiving & fall" },
  thanksgiving: { emoji: "🦃", heading: "Thanksgiving" },
  winter: { emoji: "🎄", heading: "Christmas & holiday lights" },
};

export function seasonLook(season: string): { emoji: string; heading: string } {
  return SEASON_LOOK[season] ?? { emoji: "✨", heading: season.charAt(0).toUpperCase() + season.slice(1) };
}

// One request per page load, shared by the badge, the page and the
// banners. Failure is just "no season" - this must never cost a render.
let pending: Promise<SeasonalGuide[]> | null = null;
function loadGuides(): Promise<SeasonalGuide[]> {
  pending ??= apiFetch("/seasonal-guides")
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => []);
  return pending;
}

/** Active seasons, each with its guides headline-first (the API's order).
 * Empty until loaded and whenever nothing is running. */
export function useSeasons(): { seasons: Season[]; loaded: boolean } {
  const [guides, setGuides] = useState<SeasonalGuide[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadGuides().then((g) => !cancelled && setGuides(g));
    return () => {
      cancelled = true;
    };
  }, []);
  const bySeason = new Map<string, SeasonalGuide[]>();
  for (const g of guides ?? []) bySeason.set(g.season, [...(bySeason.get(g.season) ?? []), g]);
  const seasons = [...bySeason].map(([season, list]) => ({ season, ...seasonLook(season), guides: list }));
  return { seasons, loaded: guides !== null };
}

/** A place open for a season - a haunt, a flashlight maze, a light show
 * (GET /seasonal-attractions). Our own list from each venue's site. */
export type SeasonalAttraction = {
  id: string;
  season: string;
  kind: string;
  name: string;
  venue: string | null;
  address: string;
  town: string;
  url: string;
  ticket_url: string | null;
  starts_on: string;
  ends_on: string;
  open_dates: string[] | null;
  schedule: string | null;
  price: string | null;
  scare_level: "family" | "mild" | "scary" | null;
  ages: string | null;
  note: string | null;
  verified_on: string | null;
  /** Open today: true/false, or null when the venue only says "select nights". */
  open_on_day: boolean | null;
};

// The order "Places to go" lists kinds in, each under its own heading once a
// season has more than one. A kind missing here still shows, after these.
const KIND_LABELS: [string, string][] = [
  ["turkey_trot", "Turkey trots"],
  ["race", "Races"],
  ["haunt", "Haunted houses"],
  ["hayride", "Hayrides"],
  ["trail", "Haunted trails"],
  ["corn_maze", "Corn mazes"],
  ["light_show", "Light shows"],
  ["santa", "Visit Santa"],
  ["train", "Holiday trains"],
  ["market", "Christmas markets"],
  ["tree_lighting", "Tree lightings"],
  ["parade", "Parades"],
  ["ice_rink", "Ice skating"],
  ["farm", "Farms & hayrides"],
  ["festival", "Festivals & more"],
];
const KIND_ORDER = new Map(KIND_LABELS.map(([kind], i) => [kind, i]));
const KIND_LABEL = new Map(KIND_LABELS);

export type AttractionGroup = { kind: string; label: string; attractions: SeasonalAttraction[] };

/** Attractions under their kind's heading, kinds in KIND_LABELS order. */
export function groupByKind(attractions: SeasonalAttraction[]): AttractionGroup[] {
  const byKind = new Map<string, SeasonalAttraction[]>();
  for (const a of attractions) byKind.set(a.kind, [...(byKind.get(a.kind) ?? []), a]);
  const rank = (kind: string) => KIND_ORDER.get(kind) ?? KIND_ORDER.size;
  return [...byKind]
    .map(([kind, list]) => ({
      kind,
      label: KIND_LABEL.get(kind) ?? kind.charAt(0).toUpperCase() + kind.slice(1).replace(/_/g, " "),
      attractions: list,
    }))
    .sort((a, b) => rank(a.kind) - rank(b.kind) || a.label.localeCompare(b.label));
}

/** This season's attractions still running, soonest first; [] on failure. */
export function useAttractions(season: string): { attractions: SeasonalAttraction[]; loaded: boolean } {
  const [attractions, setAttractions] = useState<SeasonalAttraction[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    setAttractions(null);
    apiFetch(`/seasonal-attractions?season=${encodeURIComponent(season)}`)
      .then((r) => (r.ok ? r.json() : []))
      .catch(() => [])
      .then((a: SeasonalAttraction[]) => !cancelled && setAttractions(a));
    return () => {
      cancelled = true;
    };
  }, [season]);
  return { attractions: attractions ?? [], loaded: attractions !== null };
}
