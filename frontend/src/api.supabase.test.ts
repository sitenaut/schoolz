import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// api.ts reads its auth mode from these two modules at import time, so
// Supabase mode has to be mocked in rather than toggled - the rest of the
// suite (api.test.ts) covers the local-token path.
vi.mock("./authConfig", () => ({ API_URL: "http://api.test", IS_SUPABASE_AUTH: true }));

const getSession = vi.fn();
vi.mock("./supabase", () => ({ supabase: { auth: { getSession: () => getSession() } } }));

function jsonResponse(status: number): Response {
  return new Response(JSON.stringify({}), { status });
}

function authOf(call: unknown[]): string | undefined {
  return (call[1] as RequestInit | undefined)?.headers as never;
}

// api.ts caches the token in a module-level variable, so each test needs a
// fresh copy of the module to start from "not known yet".
async function freshApi() {
  vi.resetModules();
  return import("./api");
}

beforeEach(() => {
  getSession.mockReset();
  getSession.mockResolvedValue({ data: { session: { access_token: "from-get-session" } } });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("apiFetch in Supabase auth mode", () => {
  it("uses the cached token without asking supabase-js for it", async () => {
    // The whole point of the cache: supabase-js serialises auth calls
    // behind one lock, so a getSession() per request made every in-flight
    // request queue behind whatever else held it (25-42s stalls in prod).
    const { apiFetch, setCachedAccessToken } = await freshApi();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    setCachedAccessToken("cached-token");
    await apiFetch("/auth/me");
    await apiFetch("/schools");

    expect(getSession).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer cached-token");
  });

  it("reads the session once when no token is cached yet, then reuses it", async () => {
    const { apiFetch } = await freshApi();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/auth/me");
    await apiFetch("/schools");

    expect(getSession).toHaveBeenCalledTimes(1);
    const headers = (fetchMock.mock.calls[1][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer from-get-session");
  });

  it("sends no Authorization header when there is no session", async () => {
    getSession.mockResolvedValue({ data: { session: null } });
    const { apiFetch } = await freshApi();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/schools");

    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("replays a 401 once with a freshly-read token", async () => {
    // A cached token can outlive its expiry if the tab slept through the
    // refresh; a 401 means the request was rejected, never processed.
    const { apiFetch, setCachedAccessToken } = await freshApi();
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(401)).mockResolvedValueOnce(jsonResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    setCachedAccessToken("stale-token");
    const res = await apiFetch("/auth/me");

    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const retried = (fetchMock.mock.calls[1][1] as RequestInit).headers as Record<string, string>;
    expect(retried.Authorization).toBe("Bearer from-get-session");
  });

  it("does not replay a 401 when the re-read token is the same one", async () => {
    // Otherwise a genuinely-unauthorised request doubles every call.
    getSession.mockResolvedValue({ data: { session: { access_token: "same-token" } } });
    const { apiFetch, setCachedAccessToken } = await freshApi();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401));
    vi.stubGlobal("fetch", fetchMock);

    setCachedAccessToken("same-token");
    const res = await apiFetch("/auth/me");

    expect(res.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("replays a 401 for a non-GET too", async () => {
    // Safe in a way the network/502 retry is not: a 401 is a rejection,
    // so the write definitively did not happen.
    const { apiFetch, setCachedAccessToken } = await freshApi();
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(401)).mockResolvedValueOnce(jsonResponse(200));
    vi.stubGlobal("fetch", fetchMock);

    setCachedAccessToken("stale-token");
    const res = await apiFetch("/survey", { method: "POST", body: "{}" });

    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
