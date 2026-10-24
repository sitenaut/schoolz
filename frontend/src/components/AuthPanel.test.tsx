// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const loginLocal = vi.fn();
vi.mock("../authConfig", () => ({ IS_SUPABASE_AUTH: false }));
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    loginLocal,
    registerLocal: vi.fn(),
    loginWithPasswordSupabase: vi.fn(),
    registerWithPasswordSupabase: vi.fn(),
    resendConfirmationEmailSupabase: vi.fn(),
    loginWithGoogle: vi.fn(),
    error: null,
  }),
}));

import { AuthPanel } from "./AuthPanel";

afterEach(() => {
  cleanup();
  loginLocal.mockReset();
});

async function signIn(ok: boolean) {
  loginLocal.mockResolvedValue(ok);
  const onSuccess = vi.fn();
  const { container } = render(
    <MemoryRouter>
      <AuthPanel mode="login" onModeChange={() => {}} onSuccess={onSuccess} />
    </MemoryRouter>,
  );
  const [identifier, password] = Array.from(container.querySelectorAll("input"));
  fireEvent.change(identifier, { target: { value: "mom@example.com" } });
  fireEvent.change(password, { target: { value: "wrong" } });
  fireEvent.submit(container.querySelector("form")!);
  await waitFor(() => expect(loginLocal).toHaveBeenCalled());
  await Promise.resolve();
  return onSuccess;
}

describe("AuthPanel", () => {
  it("stays open on a failed sign-in, so its error can be read", async () => {
    const onSuccess = await signIn(false);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("closes once signed in", async () => {
    const onSuccess = await signIn(true);
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
  });
});
