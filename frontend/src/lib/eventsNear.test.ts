import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_NEAR, DEFAULT_RADIUS, addNearParams, loadNearChoice, makeNear, saveNearChoice } from "./eventsNear";

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, String(v)),
  };
}

describe("eventsNear", () => {
  beforeEach(() => vi.stubGlobal("localStorage", memoryStorage()));

  it("assumes Cherry Hill until a location is chosen", () => {
    expect(loadNearChoice()).toEqual({ near: DEFAULT_NEAR, radius: DEFAULT_RADIUS });
  });

  it("rounds a position to about half a mile before keeping it", () => {
    const near = makeNear("your current location", 39.891537, -75.037712, "device");
    expect([near.lat, near.lng]).toEqual([39.89, -75.04]);
    saveNearChoice({ near, radius: 5 });
    expect(localStorage.getItem("schoolz_local_near_v1")).not.toContain("39.8915");
    expect(loadNearChoice()).toEqual({ near, radius: 5 });
  });

  it("remembers 'any distance' and a radius without a place", () => {
    saveNearChoice({ near: DEFAULT_NEAR, radius: null });
    expect(loadNearChoice()).toEqual({ near: DEFAULT_NEAR, radius: null });
  });

  it("falls back on junk", () => {
    localStorage.setItem("schoolz_local_near_v1", JSON.stringify({ near: { label: 3, lat: "x" }, radius: 7 }));
    expect(loadNearChoice()).toEqual({ near: DEFAULT_NEAR, radius: DEFAULT_RADIUS });
    localStorage.setItem("schoolz_local_near_v1", "{not json");
    expect(loadNearChoice()).toEqual({ near: DEFAULT_NEAR, radius: DEFAULT_RADIUS });
  });

  it("always sends the point, and the radius unless it's any distance", () => {
    const q = new URLSearchParams();
    addNearParams(q, { near: DEFAULT_NEAR, radius: 15 });
    expect(q.toString()).toBe("near_lat=39.93&near_lng=-75.02&radius_miles=15");
    const any = new URLSearchParams();
    addNearParams(any, { near: DEFAULT_NEAR, radius: null });
    expect(any.has("radius_miles")).toBe(false);
  });
});
