import { describe, expect, it } from "vitest";
import type { DistrictSummary, School } from "../types";
import { defaultTown, pickerTowns, schoolsInTown, searchSchools } from "./towns";

const districts: DistrictSummary[] = [
  { id: "ch", name: "Cherry Hill Public Schools", towns: ["Cherry Hill"] },
  { id: "vt", name: "Voorhees Township Public Schools", towns: ["Voorhees"] },
  { id: "er", name: "Eastern Camden County Regional School District", towns: ["Voorhees", "Berlin", "Gibbsboro"] },
];
const byId = new Map(districts.map((d) => [d.id, d]));
const s = (slug: string, district_id: string, school_type: string, name = slug) => ({ slug, name, short_name: null, district_id, school_type }) as unknown as School;
const schools = [
  s("bret-harte", "ch", "elementary", "Bret Harte Elementary"),
  s("east", "ch", "high", "Cherry Hill High School East"),
  s("kresson", "vt", "elementary", "Kresson Elementary"),
  s("voorhees-middle", "vt", "middle", "Voorhees Middle School"),
  s("eastern-regional", "er", "high", "Eastern Regional High School"),
];

describe("towns", () => {
  it("gives a chip only to towns with a tracked elementary school", () => {
    expect(pickerTowns(schools, byId)).toEqual(["Cherry Hill", "Voorhees"]);
  });

  it("puts the regional high school under every town it serves", () => {
    expect(schoolsInTown("Voorhees", schools, byId).map((x) => x.slug)).toEqual(["kresson", "voorhees-middle", "eastern-regional"]);
    expect(schoolsInTown("Cherry Hill", schools, byId).map((x) => x.slug)).not.toContain("eastern-regional");
  });

  it("opens on the town most picked schools are in, or none when nothing is picked", () => {
    const towns = pickerTowns(schools, byId);
    expect(defaultTown(towns, [schools[2], schools[4]], byId)).toBe("Voorhees");
    expect(defaultTown(towns, [], byId)).toBeNull();
    expect(defaultTown(["Cherry Hill"], [], byId)).toBe("Cherry Hill");
  });

  it("searches across towns and districts, ANDing words", () => {
    expect(searchSchools("eastern", schools, byId).map((x) => x.slug)).toEqual(["eastern-regional"]);
    expect(searchSchools("gibbsboro", schools, byId).map((x) => x.slug)).toEqual(["eastern-regional"]);
    expect(searchSchools("voorhees middle", schools, byId).map((x) => x.slug)).toEqual(["voorhees-middle"]);
  });
});
