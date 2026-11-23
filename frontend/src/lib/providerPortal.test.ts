import { describe, expect, it } from "vitest";
import { completeness, emptyHours, emptyPlace, emptySubmission, upkeepMissing, withDefaults } from "./providerPortal";

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

  // Same cases as test_ticking_listings_as_yours_asks_for_nothing_but_the_name.
  it("asks for nothing but the name from someone who only ticked the listings that are theirs", () => {
    const only = withDefaults({ organization_name: "Riverbend Community Action", claims: ["a", "b"] });
    expect(only.services).toEqual([]);
    expect(completeness(only, false)).toEqual({ missing_core: [], missing_optional: [], percent: 100 });
    expect(completeness(withDefaults({ claims: ["a"] }), false).missing_core).toEqual(["organization_name"]);
    const more = { ...withDefaults({ organization_name: "Riverbend", claims: ["a"] }), services: [{ type: "food_pantry", name: "", description: "" }] };
    expect(completeness(more, false).missing_core).toEqual(["services", "address", "hours", "phone", "who", "cost"]);
  });

  // Same cases as test_read_it_from_our_website_takes_the_address_as_people_type_it.
  it("wants a page from someone who asks us to read their website or feed", () => {
    expect(upkeepMissing({})).toBe(false);
    expect(upkeepMissing({ upkeep: { mode: "portal", urls: [], note: null } })).toBe(false);
    expect(upkeepMissing({ upkeep: { mode: "website", urls: [" "], note: null } })).toBe(true);
    expect(upkeepMissing({ upkeep: { mode: "feed", urls: ["ourpantry.org/feed.ics"], note: null } })).toBe(false);
  });

  // Same cases as test_a_program_can_carry_the_hours_who_and_cost_the_organization_left_out.
  it("lets programs carry the hours, who and cost the organization left out", () => {
    const blank = { ...full(), hours: emptyHours(), who: emptySubmission().who, cost: { kind: null, amount: null } };
    expect(completeness(blank, false).missing_core).toEqual(["hours", "who", "cost"]);
    const own = {
      ...blank,
      services: [{ ...blank.services[0], hours: { mode: "appointment" as const, weekly: {} }, who: { ...emptySubmission().who, seniors: true }, cost: { kind: "free" as const, amount: null } }],
    };
    expect(completeness(own, false).missing_core).toEqual([]);
    const second = { ...own, services: [...own.services, { type: "clothing", name: "Closet", description: "Coats." }] };
    expect(completeness(second, false).missing_core).toEqual(["hours", "who", "cost"]);
    const place = { ...full(), services: [{ type: "food_pantry", name: "P", description: "D", place: { ...emptyPlace(), address: "1 Main St" } }] };
    expect(completeness(place, false).missing_core).toEqual(["services"]);
    const monthly = { ...full(), services: [{ type: "food_pantry", name: "P", description: "D", hours: { ...emptyHours(), mode: "monthly" as const } }] };
    expect(completeness(monthly, false).missing_core).toEqual(["services"]);
  });
});
