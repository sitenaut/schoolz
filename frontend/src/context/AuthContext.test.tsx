// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("../authConfig", () => ({ API_URL: "http://api.test", IS_SUPABASE_AUTH: false }));
vi.mock("../supabase", () => ({ supabase: null }));
vi.mock("../lib/track", () => ({ trackEvent: () => {}, trackMeasurement: () => {} }));

// /auth/me answers only when the test says so.
const me = vi.hoisted(() => ({ resolve: (_res: Response) => {} }));
vi.mock("../api", () => ({
  apiFetch: () =>
    new Promise<Response>((resolve) => {
      me.resolve = resolve;
    }),
  setLocalToken: () => {},
  clearLocalToken: () => {},
  getLocalToken: () => "token",
  setCachedAccessToken: () => {},
}));

import { AuthProvider, useAuth } from "./AuthContext";

function Probe() {
  const { user, logout } = useAuth();
  return (
    <div>
      <span data-testid="who">{user ? user.username : "nobody"}</span>
      <button onClick={() => void logout()}>Sign out</button>
    </div>
  );
}

const answer = () => new Response(JSON.stringify({ id: "u1", username: "previous" }), { status: 200 });

afterEach(cleanup);

describe("AuthProvider", () => {
  it("shows the account /auth/me returns", async () => {
    render(<AuthProvider><Probe /></AuthProvider>);
    await act(async () => me.resolve(answer()));
    expect(screen.getByTestId("who").textContent).toBe("previous");
  });

  it("ignores an /auth/me that answers after sign-out", async () => {
    // A token-refresh check still in flight put the signed-out account back
    // in the header.
    render(<AuthProvider><Probe /></AuthProvider>);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign out" })));
    await act(async () => me.resolve(answer()));
    expect(screen.getByTestId("who").textContent).toBe("nobody");
  });
});
