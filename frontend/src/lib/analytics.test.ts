import { describe, expect, it } from "vitest";
import { analyticsPath, shouldTrack } from "./analytics";

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
