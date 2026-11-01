import { describe, expect, it } from "vitest";
import { groupByKind, seasonLook, type SeasonalAttraction } from "./seasonal";

function attraction(kind: string, name: string): SeasonalAttraction {
  return {
    id: `${kind}-${name}`,
    season: "fall",
    kind,
    name,
    venue: null,
    address: "1 Main St, Haddonfield, NJ 08033",
    town: "Haddonfield",
    url: "https://example.com/",
    ticket_url: null,
    starts_on: "2026-11-26",
    ends_on: "2026-11-26",
    open_dates: ["2026-11-26"],
    schedule: null,
    price: null,
    scare_level: null,
    ages: null,
    note: null,
    verified_on: null,
    open_on_day: false,
  };
}

describe("groupByKind", () => {
  it("puts kinds in a fixed order, keeping each kind's own order", () => {
    const groups = groupByKind([
      attraction("parade", "Thanksgiving Day Parade"),
      attraction("turkey_trot", "Moorestown"),
      attraction("festival", "Harvest weekend"),
      attraction("turkey_trot", "Haddonfield"),
    ]);
    expect(groups.map((g) => g.label)).toEqual(["Turkey trots", "Parades", "Festivals & more"]);
    expect(groups[0].attractions.map((a) => a.name)).toEqual(["Moorestown", "Haddonfield"]);
  });

  it("still shows a kind it has no label for, last", () => {
    const groups = groupByKind([attraction("sleigh_ride", "Sleigh rides"), attraction("santa", "Mall Santa")]);
    expect(groups.map((g) => g.label)).toEqual(["Visit Santa", "Sleigh ride"]);
  });
});

describe("seasonLook", () => {
  it("gives November the turkey, and an unknown season a generic look", () => {
    expect(seasonLook("fall").emoji).toBe("🦃");
    expect(seasonLook("spring")).toEqual({ emoji: "✨", heading: "Spring" });
  });
});
