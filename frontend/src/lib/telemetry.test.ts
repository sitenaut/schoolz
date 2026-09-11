import { describe, expect, it } from "vitest";
import { scrubUrl } from "./telemetry";

describe("scrubUrl", () => {
  it("drops the entire hash - Supabase OAuth returns tokens there", () => {
    const result = scrubUrl("https://schoolz.sitenaut.com/#access_token=abc123&refresh_token=xyz&type=bearer");
    expect(result).toBe("https://schoolz.sitenaut.com/");
    expect(result).not.toContain("access_token");
    expect(result).not.toContain("abc123");
  });

  it("strips sensitive query params but keeps others", () => {
    expect(scrubUrl("https://schoolz-api.sitenaut.com/gmail/callback?code=secret123&state=xyz&foo=bar")).toBe(
      "https://schoolz-api.sitenaut.com/gmail/callback?foo=bar"
    );
  });

  it("strips access_token/refresh_token query params on a relative path", () => {
    expect(scrubUrl("/gmail/callback?access_token=secret&refresh_token=other")).toBe("/gmail/callback");
  });

  it("rewrites an invite token path to its route template", () => {
    expect(scrubUrl("https://schoolz.sitenaut.com/invites/a1b2c3d4e5f6")).toBe(
      "https://schoolz.sitenaut.com/invites/:token"
    );
    expect(scrubUrl("/invites/a1b2c3d4e5f6?foo=bar")).toBe("/invites/:token?foo=bar");
  });

  it("leaves an ordinary url/path untouched", () => {
    expect(scrubUrl("https://schoolz.sitenaut.com/schools/bret-harte-elementary")).toBe(
      "https://schoolz.sitenaut.com/schools/bret-harte-elementary"
    );
    expect(scrubUrl("/calendar?school=bret-harte-elementary")).toBe("/calendar?school=bret-harte-elementary");
  });

  it("handles a bare route template with no query/hash", () => {
    expect(scrubUrl("/schools/:schoolId")).toBe("/schools/:schoolId");
  });

  it("combines hash-stripping and token-stripping together", () => {
    expect(scrubUrl("https://schoolz.sitenaut.com/?code=abc#access_token=def")).toBe(
      "https://schoolz.sitenaut.com/"
    );
  });
});

describe("FaroRoutes", () => {
  it("is the plain react-router Routes when RUM is off (no VITE_FARO_URL)", async () => {
    const { Routes } = await import("react-router-dom");
    const { FaroRoutes } = await import("./telemetry");
    // Regression: faro's own FaroRoutes renders an internal Routes ref that
    // is undefined until initializeFaro runs - blanked every page locally.
    expect(FaroRoutes).toBe(Routes);
  });
});
