import { describe, expect, it } from "vitest";
import { scrubDeep, scrubUrl } from "./telemetry";

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

  it("hides which Localz resource was opened", () => {
    expect(scrubUrl("https://schoolz.sitenaut.com/es/localz/r/7fa184cb-8cb0")).toBe("https://schoolz.sitenaut.com/es/localz/r/:id");
    expect(scrubUrl("/localz/food")).toBe("/localz/food");
  });

  it("hides which Neighborz bill or hold, in pages and API calls", () => {
    expect(scrubUrl("/localz/bills/hold/2f1c9a3e-1b2c-4d5e-8f90-123456789abc")).toBe("/localz/bills/hold/:id");
    expect(scrubUrl("https://schoolz-api.sitenaut.com/bills/holds/2f1c9a3e-1b2c-4d5e-8f90-123456789abc/paid")).toBe(
      "https://schoolz-api.sitenaut.com/bills/holds/:id/paid",
    );
    expect(scrubUrl("https://schoolz-api.sitenaut.com/bills/2f1c9a3e-1b2c-4d5e-8f90-123456789abc/hold")).toBe(
      "https://schoolz-api.sitenaut.com/bills/:id/hold",
    );
    expect(scrubUrl("/localz/bills/mine")).toBe("/localz/bills/mine");
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

  it("scrubs a path carried in ?next=, e.g. a connect code during sign-in", () => {
    const result = scrubUrl("https://schoolz.sitenaut.com/login?next=%2Fconnect%3Fcode%3DWXYZ-1234");
    expect(result).not.toContain("WXYZ");
    expect(new URL(result).searchParams.get("next")).toBe("/connect");
    expect(scrubUrl("/register?next=%2Finvites%2Fabc123")).not.toContain("abc123");
    // An ordinary next is left exactly as it was.
    expect(scrubUrl("/login?next=%2Ffamily")).toBe("/login?next=%2Ffamily");
  });

  it("combines hash-stripping and token-stripping together", () => {
    expect(scrubUrl("https://schoolz.sitenaut.com/?code=abc#access_token=def")).toBe(
      "https://schoolz.sitenaut.com/"
    );
  });
});

describe("token-bearing paths", () => {
  it("collapses every invite and approval-code route, page or API", () => {
    expect(scrubUrl("/student-invites/abc123")).toBe("/student-invites/:token");
    expect(scrubUrl("https://api.example/student-account-invites/abc123/accept")).toBe("https://api.example/student-account-invites/:token/accept");
    expect(scrubUrl("https://api.example/invites/abc123/accept")).toBe("https://api.example/invites/:token/accept");
    expect(scrubUrl("/capture-devices/requests/WXYZ-1234/approve")).toBe("/capture-devices/requests/:code/approve");
    expect(scrubUrl("/admin/api-keys/requests/WXYZ-1234")).toBe("/admin/api-keys/requests/:code");
    expect(scrubUrl("/admin/secret-requests/WXYZ-1234/deny")).toBe("/admin/secret-requests/:code/deny");
    expect(scrubUrl("/admin/secret-requests/poll")).toBe("/admin/secret-requests/poll");
  });

  it("scrubs a trace span's URL attribute, however deep it sits", () => {
    const payload = {
      resourceSpans: [{ scopeSpans: [{ spans: [{ attributes: [{ key: "http.url", value: { stringValue: "https://api.example/invites/abc123/accept" } }] }] }] }],
    };
    scrubDeep(payload);
    expect(JSON.stringify(payload)).not.toContain("abc123");
    expect(JSON.stringify(payload)).toContain("/invites/:token/accept");
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
