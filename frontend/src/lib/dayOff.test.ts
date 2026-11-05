import { describe, expect, it } from "vitest";
import { dayOffNear, planDayOff, townOf } from "./dayOff";
import { DEFAULT_NEAR, DEFAULT_RADIUS, makeNear } from "./eventsNear";
import type { School, SchoolToday } from "../types";

function card(name: string, type: string, daysOff: [string, string | null][], extra: Partial<School> = {}): SchoolToday {
  return {
    school: { id: name, slug: name, name, short_name: name, school_type: type, address: null, ...extra } as School,
    days_off: daysOff.map(([date, label]) => ({ date, label })),
  } as SchoolToday;
}

describe("planDayOff", () => {
  const njea: [string, string | null][] = [
    ["2026-11-05", "NJEA Convention"],
    ["2026-11-06", "NJEA Convention"],
  ];

  it("is today's closure until mid-afternoon, then the next day of it", () => {
    const cards = [card("Beck", "middle", njea)];
    expect(planDayOff(cards, "2026-11-05", 9)).toMatchObject({ date: "2026-11-05", daysAhead: 0, label: "NJEA Convention", allOut: true, audience: "kids" });
    expect(planDayOff(cards, "2026-11-05", 16)).toMatchObject({ date: "2026-11-06", daysAhead: 1 });
    expect(planDayOff(cards, "2026-11-06", 16)).toBeNull();
  });

  it("starts a few days ahead, not a week", () => {
    const cards = [card("Beck", "middle", njea)];
    expect(planDayOff(cards, "2026-11-02", 9)?.date).toBe("2026-11-05");
    expect(planDayOff(cards, "2026-11-01", 9)).toBeNull();
  });

  it("names the schools that are out when not all of them are, and asks about teens only for high schools", () => {
    const cards = [card("East", "high", [["2026-11-11", "Veterans Day"]]), card("Kingston", "elementary", [])];
    const plan = planDayOff(cards, "2026-11-10", 8)!;
    expect(plan.allOut).toBe(false);
    expect(plan.schools.map((s) => s.name)).toEqual(["East"]);
    expect(plan.audience).toBe("teens");
    const both = planDayOff([card("East", "high", [["2026-11-11", null]]), card("Beck", "middle", [["2026-11-11", "Veterans Day"]])], "2026-11-10", 8)!;
    expect(both).toMatchObject({ allOut: true, audience: "kids", label: "Veterans Day" });
  });

  it("is nothing without a closure", () => {
    expect(planDayOff([card("Beck", "middle", [])], "2026-11-05", 9)).toBeNull();
    expect(planDayOff([{ ...card("Beck", "middle", []), days_off: undefined }], "2026-11-05", 9)).toBeNull();
  });
});

describe("townOf", () => {
  it("takes the town before the state", () => {
    expect(townOf("1200 Brace Rd, Cherry Hill, NJ 08034")).toBe("Cherry Hill");
    expect(townOf("100 Main St., Haddonfield, New Jersey 08033")).toBe("Haddonfield");
    expect(townOf("Somewhere")).toBeNull();
    expect(townOf(null)).toBeNull();
  });
});

describe("dayOffNear", () => {
  const beck = card("Beck", "middle", [], { address: "950 Cropwell Rd, Cherry Hill, NJ 08003", latitude: 39.9101, longitude: -74.9601 }).school;
  const fallback = { near: DEFAULT_NEAR, radius: DEFAULT_RADIUS };

  it("measures from the school, rounded, unless the visitor chose a place on /local", () => {
    const fromSchool = dayOffNear(fallback, [beck]);
    expect(fromSchool.choice.near).toMatchObject({ lat: 39.91, lng: -74.96 });
    expect(fromSchool).toMatchObject({ place: "Cherry Hill", town: "Cherry Hill" });

    const home = { near: makeNear("Haddonfield, NJ 08033", 39.89, -75.03, "place"), radius: 10 };
    expect(dayOffNear(home, [beck])).toEqual({ choice: home, place: "Haddonfield, NJ 08033", town: "Haddonfield, NJ 08033" });
  });

  it("uses the device's position as is, and gives the chatbot the school's town", () => {
    const device = { near: makeNear("your current location", 39.9, -75.0, "device"), radius: 5 };
    expect(dayOffNear(device, [beck])).toEqual({ choice: device, place: null, town: "Cherry Hill" });
  });

  it("falls back to Cherry Hill for a school with no position", () => {
    const unplaced = card("New", "elementary", [], { address: "1 School Ln, Lumberton, NJ 08048" }).school;
    expect(dayOffNear(fallback, [unplaced])).toEqual({ choice: fallback, place: DEFAULT_NEAR.label, town: "Lumberton" });
  });
});
