// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAuthClient } from "./supabase";

// Every signed-in visitor's session was saved by supabase-js. These pin down
// what keeps it working with auth-js alone: the same storage key, auth URL
// and API key headers. Each test uses its own project ref, since auth-js
// warns about two clients on one storage key.

function jwt(claims: object): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(claims)}.c2ln`;
}

const user = { id: "u1", aud: "authenticated", role: "authenticated", email: "a@example.com", app_metadata: {}, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" };

function session(token: string) {
  const exp = Math.floor(Date.now() / 1000) + 3600;
  return { access_token: jwt({ sub: "u1", exp, aal: "aal1", t: token }), refresh_token: "r1", expires_in: 3600, expires_at: exp, token_type: "bearer", user };
}

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("createAuthClient", () => {
  it("reads a session supabase-js saved, without a network call", async () => {
    const saved = session("old-client");
    localStorage.setItem("sb-oldref-auth-token", JSON.stringify(saved));
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);

    const auth = createAuthClient("https://oldref.supabase.co", "sb_publishable_k");
    const { data } = await auth.getSession();
    auth.stopAutoRefresh();

    expect(data.session?.access_token).toBe(saved.access_token);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("signs in against <project>/auth/v1 with the API key and saves under the same key", async () => {
    const issued = session("new-sign-in");
    const fetch = vi.fn(async () => new Response(JSON.stringify(issued), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);

    const auth = createAuthClient("https://newref.supabase.co", "sb_publishable_k");
    const { error } = await auth.signInWithPassword({ email: "a@example.com", password: "pw" });
    auth.stopAutoRefresh();

    expect(error).toBeNull();
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://newref.supabase.co/auth/v1/token?grant_type=password");
    expect(init.headers).toMatchObject({ apikey: "sb_publishable_k", Authorization: "Bearer sb_publishable_k" });
    expect(JSON.parse(localStorage.getItem("sb-newref-auth-token") ?? "{}").access_token).toBe(issued.access_token);
  });
});
