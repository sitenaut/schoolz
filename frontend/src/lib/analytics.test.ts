import { describe, expect, it } from "vitest";
import { analyticsPath, schoolViews, shouldTrack } from "./analytics";

describe("analyticsPath", () => {
  it("keeps a public school's real path so landing pages are reportable", () => {
    expect(analyticsPath("/schools/bret-harte-elementary", "")).toBe("/schools/bret-harte-elementary");
  });

  it("keeps utm_* for campaign attribution and drops everything else", () => {
    expect(analyticsPath("/calendar", "?utm_source=Facebook&utm_campaign=fall&fbclid=abc&school=x&q=iep")).toBe(
      "/calendar?utm_source=Facebook&utm_campaign=fall"
    );
  });

  it("collapses invite tokens to their template", () => {
    expect(analyticsPath("/invites/s3cr3t-token", "?next=/x")).toBe("/invites/:token");
    expect(analyticsPath("/student-invites/abc", "")).toBe("/student-invites/:token");
  });

  it("reports personal and admin routes as their section only", () => {
    expect(analyticsPath("/account/security", "?code=1")).toBe("/account");
    expect(analyticsPath("/admin/scans", "")).toBe("/admin");
    expect(analyticsPath("/kids/123/work", "")).toBe("/kids");
    expect(analyticsPath("/children", "")).toBe("/children");
  });
});

describe("shouldTrack", () => {
  const base = { id: "G-TEST", webdriver: false, hostname: "schoolz.sitenaut.com", siteHostname: "schoolz.sitenaut.com" };

  it("tracks a real browser on the production host", () => {
    expect(shouldTrack(base)).toBe(true);
  });

  it("is off with no measurement id (local, vitest)", () => {
    expect(shouldTrack({ ...base, id: "" })).toBe(false);
  });

  it("skips automation, including the prerender/Playwright pass", () => {
    expect(shouldTrack({ ...base, webdriver: true })).toBe(false);
  });

  it("skips any other host: localhost, previews, the internal prerender address", () => {
    expect(shouldTrack({ ...base, hostname: "localhost" })).toBe(false);
    expect(shouldTrack({ ...base, hostname: "schoolz-web.internal" })).toBe(false);
  });
});

describe("schoolViews", () => {
  const harte = { id: "11111111-aaaa", slug: "bret-harte-elementary" };
  const beck = { id: "22222222-bbbb", slug: "beck-middle" };
  const all = [harte, beck];

  it("credits every school card shown on Today", () => {
    expect(schoolViews("/", all, [harte, beck])).toEqual({ path: "/", surface: "today", slugs: ["bret-harte-elementary", "beck-middle"] });
  });

  it("reports a school opened by id under its slug, so it isn't split in two", () => {
    expect(schoolViews("/schools/11111111-aaaa", all, [])).toEqual({
      path: "/schools/bret-harte-elementary",
      surface: "school_page",
      slugs: ["bret-harte-elementary"],
    });
  });

  it("credits the school for one of its class pages", () => {
    expect(schoolViews("/schools/beck-middle/class-of-2028", all, [])).toEqual({
      path: "/schools/beck-middle/class-of-2028",
      surface: "class_page",
      slugs: ["beck-middle"],
    });
  });

  it("credits no school on pages that aren't per-school", () => {
    expect(schoolViews("/calendar", all, [harte]).slugs).toEqual([]);
    expect(schoolViews("/schools", all, [harte]).slugs).toEqual([]);
  });
});
