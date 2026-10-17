import { describe, expect, it } from "vitest";
import { boxAround, countiesForAreaCode, milesBetween, orderNearby, whereForPoint, whereForZip } from "./localzWhere";

describe("Set my location, worked out on the device", () => {
  it("turns a New Jersey ZIP into its county", async () => {
    expect((await whereForZip("07075"))?.county).toBe("Bergen"); // Wood-Ridge
    expect((await whereForZip("07074"))?.county).toBe("Bergen"); // Moonachie
    expect((await whereForZip(" 08034 "))?.county).toBe("Camden");
    expect(await whereForZip("10001")).toBeNull(); // Manhattan
    expect(await whereForZip("0707")).toBeNull();
  });

  it("narrows an area code to the counties it covers, and knows non-NJ codes", () => {
    expect(countiesForAreaCode("201")).toEqual(["Bergen", "Hudson"]);
    expect(countiesForAreaCode("856")).toContain("Camden");
    expect(countiesForAreaCode("212")).toBeNull();
  });

  it("places the phone at its nearest NJ ZIP's county, rounded, or nowhere outside NJ", async () => {
    const moonachie = await whereForPoint(40.84123, -74.05678);
    expect(moonachie?.county).toBe("Bergen");
    expect(moonachie?.lat).toBe(40.84);
    expect(moonachie?.lon).toBe(-74.06);
    expect(await whereForPoint(41.8781, -87.6298)).toBeNull(); // Chicago
  });
});

describe("Closest first, measured on the device", () => {
  it("sends only a box snapped to the half-degree grid, wide enough for the radius", () => {
    const box = boxAround(39.93, -75.01, 20); // Cherry Hill
    for (const edge of Object.values(box)) expect(Number.isInteger(edge * 2)).toBe(true);
    expect(box.south).toBeLessThanOrEqual(39.93 - 20 / 69);
    expect(box.north).toBeGreaterThanOrEqual(39.93 + 20 / 69);
    expect(box.west).toBeLessThanOrEqual(-75.01 - 20 / 53);
    const wide = boxAround(39.93, -75.01, 50);
    expect(wide.north - wide.south).toBeLessThanOrEqual(2);
    expect(wide.east - wide.west).toBeLessThanOrEqual(2.5);
  });

  it("orders by distance, keeps far statewide offices last, and drops other far places", () => {
    const rows = orderNearby(
      [
        ["far", 40.5, -74.4, false],
        ["two", 39.95, -75.05, false],
        ["state", 40.22, -74.76, true],
        ["one", 39.931, -75.012, false],
      ],
      39.93,
      -75.01,
      10,
    );
    expect(rows.map((r) => r.id)).toEqual(["one", "two", "state"]);
    expect(rows[0].miles).toBeLessThan(0.2);
    expect(milesBetween(39.93, -75.01, 40.22, -74.76)).toBeGreaterThan(20);
  });
});
