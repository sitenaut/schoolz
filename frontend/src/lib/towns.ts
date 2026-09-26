import type { DistrictSummary, School } from "../types";

/** Towns whose kids can attend this school - its district's towns. */
export function townsForSchool(school: School, districtsById: Map<string, DistrictSummary>): string[] {
  return (school.district_id && districtsById.get(school.district_id)?.towns) || [];
}

/** Picker chips: a town gets one only once it has an elementary school we
 * track, so a town served here only by a shared regional high school
 * (Berlin and Gibbsboro, via Eastern) doesn't get a chip holding one
 * school - that school is still one search away. */
export function pickerTowns(schools: School[], districtsById: Map<string, DistrictSummary>): string[] {
  const towns = new Set<string>();
  for (const s of schools) {
    if (s.school_type !== "elementary") continue;
    for (const t of townsForSchool(s, districtsById)) towns.add(t);
  }
  return [...towns].sort((a, b) => a.localeCompare(b));
}

export function schoolsInTown(town: string, schools: School[], districtsById: Map<string, DistrictSummary>): School[] {
  return schools.filter((s) => townsForSchool(s, districtsById).includes(town));
}

/** The chip to open on: wherever most already-picked schools are, so a
 * returning visitor lands on their own town. Null when nothing is picked
 * and there's a real choice to make. */
export function defaultTown(towns: string[], picked: School[], districtsById: Map<string, DistrictSummary>): string | null {
  if (towns.length === 1) return towns[0];
  let best: string | null = null;
  let bestCount = 0;
  for (const t of towns) {
    const n = picked.filter((s) => townsForSchool(s, districtsById).includes(t)).length;
    if (n > bestCount) {
      best = t;
      bestCount = n;
    }
  }
  return best;
}

/** Search spans every town; ANDs words across name, short name, town and district. */
export function searchSchools(q: string, schools: School[], districtsById: Map<string, DistrictSummary>): School[] {
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return schools;
  return schools.filter((s) => {
    const d = s.district_id ? districtsById.get(s.district_id) : undefined;
    const hay = [s.name, s.short_name ?? "", d?.name ?? "", ...(d?.towns ?? [])].join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** "Cherry Hill & Voorhees" - the top two towns, for copy and SEO text. */
export function townsLabel(towns: string[]): string {
  if (!towns.length) return "South Jersey";
  return towns.slice(0, 2).join(" & ");
}
