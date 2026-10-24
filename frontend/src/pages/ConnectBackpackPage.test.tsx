// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// One object, as AuthContext keeps it: the page refetches when `user` changes.
const auth = { user: { id: "mom", email: "mom@example.com" }, loading: false };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth }));

const calls: { path: string; init?: RequestInit }[] = [];
let sameNetwork = true;
vi.mock("../api", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    const status = path.endsWith("/approve") ? "approved" : "pending";
    const body = { user_code: "BCDF-GHJK", client_name: "Backpack Capture on Windows", created_at: "", expires_at: "", status, same_network: sameNetwork };
    return { ok: true, status: 200, json: async () => body };
  },
}));

import { ConnectBackpackPage } from "./ConnectBackpackPage";

afterEach(() => {
  cleanup();
  calls.length = 0;
});

function open() {
  render(
    <MemoryRouter initialEntries={["/connect?code=BCDF-GHJK"]}>
      <ConnectBackpackPage />
    </MemoryRouter>,
  );
}

describe("ConnectBackpackPage", () => {
  it("is one click when the request came from this connection", async () => {
    sameNetwork = true;
    open();
    expect(await screen.findByText("BCDF-GHJK")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/approve"))?.init?.body).toBeUndefined();
  });

  it("hides the code and wants it typed when the request came from elsewhere", async () => {
    sameNetwork = false;
    open();
    const field = await screen.findByLabelText("Code from Backpack Capture");
    // A parent sent a stranger's link must not be able to read it off the page.
    expect(screen.queryByText("BCDF-GHJK")).toBeNull();
    const connect = screen.getByRole("button", { name: "Connect" }) as HTMLButtonElement;
    expect(connect.disabled).toBe(true);

    fireEvent.change(field, { target: { value: "bcdf ghjk" } });
    expect(connect.disabled).toBe(false);
    fireEvent.click(connect);
    await waitFor(() => expect(calls.some((c) => c.path.endsWith("/approve"))).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.path.endsWith("/approve"))?.init?.body))).toEqual({ typed_code: "bcdf ghjk" });
  });
});
