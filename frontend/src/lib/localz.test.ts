import { describe, expect, it } from "vitest";
import { HELP_NOW, LOCALZ_CATEGORIES, confirmedLabel, helpLineHref, isFree, isLocalzPath, mapsHref, telHref } from "./localz";

describe("isLocalzPath", () => {
  it("covers Localz and its Events tab, nothing else", () => {
    expect(isLocalzPath("/localz")).toBe(true);
    expect(isLocalzPath("/localz/food")).toBe(true);
    expect(isLocalzPath("/localz/r/abc")).toBe(true);
    expect(isLocalzPath("/local")).toBe(true);
    expect(isLocalzPath("/localzzz")).toBe(false);
    expect(isLocalzPath("/lunch")).toBe(false);
    expect(isLocalzPath("/")).toBe(false);
  });
});

describe("resource display helpers", () => {
  it("reads NJ 211's 'None' as free, and a real fee as a fee", () => {
    expect(isFree("None")).toBe(true);
    expect(isFree("Free")).toBe(true);
    expect(isFree("No fees")).toBe(true);
    expect(isFree("$5 per visit")).toBe(false);
    expect(isFree("Nonetheless a sliding scale applies")).toBe(false);
    expect(isFree(null)).toBe(false);
  });
  it("dials digits only", () => {
    expect(telHref("856-424-1333")).toBe("tel:8564241333");
    expect(telHref("(609) 292-3717 ext 2")).toBe("tel:60929237172");
  });
  it("says when a listing was last confirmed, to the month", () => {
    expect(confirmedLabel("2026-02-27", "en-US")).toBe("February 2026");
    expect(confirmedLabel(null, "en-US")).toBeNull();
  });
  it("builds a map link only from an address it has", () => {
    expect(mapsHref({ address: "6 E Miami Ave", city: "Cherry Hill", postal_code: "08034" })).toContain("6%20E%20Miami%20Ave%2C%20Cherry%20Hill%2C%2008034");
    expect(mapsHref({ address: null, city: null, postal_code: null })).toBeNull();
  });
  it("matches the backend's category keys", () => {
    // backend/resources/categories.py CATEGORIES, in nav order.
    expect(LOCALZ_CATEGORIES.map((c) => c.key)).toEqual(["food", "english", "housing-bills", "health", "kids-family", "money-work", "legal-safety", "everyday-needs"]);
  });
});

describe("help lines", () => {
  it("calls the phone lines and texts the text line with its keyword", () => {
    const hrefs = HELP_NOW.map(helpLineHref);
    expect(hrefs).toContain("tel:18005727233");
    expect(hrefs).toContain("sms:88788?&body=BEGIN");
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
