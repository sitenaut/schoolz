// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { countVisit, visitSource } from "./visits";

function sentSource(fetchMock: ReturnType<typeof vi.fn>): string {
  const init = fetchMock.mock.calls[0][1] as RequestInit;
  return JSON.parse(init.body as string).source;
}

describe("visit source", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    // No sendBeacon, so countVisit falls back to fetch and the body is readable.
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: undefined });
    fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("labels a session that starts from one of our own pages self, not team", () => {
    vi.spyOn(document, "referrer", "get").mockReturnValue(`https://${window.location.hostname}/calendar`);
    expect(visitSource()).toBe("self");
  });

  it("counts a browser flagged as the team's under team", () => {
    localStorage.setItem("schoolz_internal", "1");
    countVisit("/calendar");
    expect(sentSource(fetchMock)).toBe("team");
  });

  it("counts everyone else by where they came from", () => {
    countVisit("/calendar");
    expect(sentSource(fetchMock)).toBe("direct");
  });
});
