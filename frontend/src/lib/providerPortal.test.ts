import { describe, expect, it } from "vitest";
import { completeness, emptySubmission, withDefaults } from "./providerPortal";

// Mirrors backend resources/portal.py completeness(); the same form scores
// the same on both sides (tests/test_provider_portal.py uses this one).
const full = () =>
  withDefaults({
    organization_name: "Maple Street Pantry",
    services: [{ type: "food_pantry", name: "Saturday Pantry", description: "Groceries." }],
    address_kind: "public",
    address: "12 Maple St",
    city: "Cherry Hill",
    hours: { mode: "weekly", weekly: { sat: [{ open: "09:00", close: "12:00" }] } },
    phone: "856-555-0142",
    who: { ...emptySubmission().who, open_to_anyone: true },
    cost: { kind: "free", amount: null },
    website: "https://maplepantry.org",
    email: "hello@maplepantry.org",
  });

describe("provider form completeness", () => {
  it("counts the required core twice as heavily as the optional fields", () => {
    const c = completeness(full(), false);
    expect(c.missing_core).toEqual([]);
    expect(c.percent).toBe(76); // 7 core x2 + 2 optional, of 21
  });

  it("says what's missing from a half-done draft", () => {
    expect(completeness(emptySubmission(), false).missing_core).toEqual(["organization_name", "services", "address", "hours", "phone", "who", "cost"]);
  });

  it("needs a phone for call-for-hours and a private address for a confidential place", () => {
    const s = { ...full(), hours: { mode: "call" as const, weekly: {} }, phone: "" };
    expect(completeness(s, false).missing_core).toEqual(["hours", "phone"]);
    const hidden = { ...full(), address_kind: "confidential" as const, address: null, city: null, service_area_counties: ["Camden"] };
    expect(completeness(hidden, false).missing_core).toEqual(["address"]);
    expect(completeness(hidden, true).missing_core).toEqual([]);
  });

  it("wants an amount when there's a fee", () => {
    expect(completeness({ ...full(), cost: { kind: "fee", amount: null } }, false).missing_core).toEqual(["cost"]);
  });
});
