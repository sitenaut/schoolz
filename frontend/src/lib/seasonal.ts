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

// A season with no entry here still works, with a generic look.
const SEASON_LOOK: Record<string, { emoji: string; heading: string }> = {
  halloween: { emoji: "🎃", heading: "Halloween & fall" },
  fall: { emoji: "🍂", heading: "Fall & Thanksgiving" },
  thanksgiving: { emoji: "🦃", heading: "Thanksgiving" },
  winter: { emoji: "🎄", heading: "Holiday lights" },
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
